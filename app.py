import os
import sys
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Allow `python backend/app.py` to work on Windows by ensuring project root is on sys.path.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.evaluator import Evaluator
from backend.gemini_service import GeminiAPIError, GeminiService
from backend.utils import utc_now_iso
from backend.yolo_service import YoloService


app = Flask(__name__)
CORS(app)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("ai-interview")

ROLES = [
    "Python Developer",
    "Frontend Developer",
    "Backend Developer",
    "Full Stack Developer",
    "Data Analyst",
    "Data Scientist",
    "Machine Learning Engineer",
    "DevOps Engineer",
    "Software Tester (QA Engineer)",
    "Cybersecurity Analyst",
    "HR",
]
DEFAULT_QUESTION_COUNT = 10

FRONTEND_DIR = os.path.join(_ROOT, "frontend")

gemini = GeminiService()
evaluator = Evaluator()
yolo = YoloService()


@dataclass
class Session:
    id: str
    role: str
    created_at: str
    questions: list[dict[str, Any]] = field(default_factory=list)
    current_index: int = 0
    answers: list[dict[str, Any]] = field(default_factory=list)
    proctoring: dict[str, Any] = field(default_factory=lambda: {"tab_switches": 0})


SESSIONS: dict[str, Session] = {}


def _bad_request(msg: str, status: int = 400):
    return jsonify({"error": msg}), status


@app.errorhandler(Exception)
def handle_unexpected_error(e: Exception):
    logger.exception("Unhandled backend error")
    return jsonify({"error": "Internal server error. Check backend logs for details."}), 500


@app.get("/api/roles")
def get_roles():
    return jsonify({"roles": ROLES})


@app.post("/api/session/start")
def start_session():
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form

    role = (payload.get("role") or "").strip()
    try:
        question_count = int(payload.get("question_count") or DEFAULT_QUESTION_COUNT)
    except (TypeError, ValueError):
        return _bad_request("question_count must be a valid integer.")

    resume_text = payload.get("resume_text") or ""
    resume_file = request.files.get("resume")
    if resume_file and resume_file.filename:
        filename = resume_file.filename
        upload_dir = os.path.join(_ROOT, "backend", "uploads", "resumes")
        os.makedirs(upload_dir, exist_ok=True)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(upload_dir, unique_filename)
        resume_file.save(filepath)

        ext = os.path.splitext(filename)[1].lower()
        try:
            if ext == '.pdf':
                import PyPDF2
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    resume_text = " ".join(page.extract_text() for page in reader.pages if page.extract_text())
            elif ext in ['.doc', '.docx']:
                import docx2txt
                resume_text = docx2txt.process(filepath)
            elif ext == '.txt':
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    resume_text = f.read()
        except Exception as e:
            logger.error(f"Failed to extract text from {filename}: {e}")

    resume_text = (resume_text or "").strip()

    if role not in ROLES:
        return _bad_request("Invalid role. Choose one of: " + ", ".join(ROLES))

    if question_count < 5:
        question_count = 5
    if question_count > 15:
        question_count = 15

    try:
        questions = gemini.generate_questions(role=role, count=question_count, resume_text=resume_text)
    except GeminiAPIError as e:
        logger.exception("Gemini question generation failed")
        if e.kind == "invalid_api_key":
            return jsonify({"error": "Gemini API key is invalid. Update GEMINI_API_KEY in .env."}), 401
        if e.kind == "quota_exceeded":
            return jsonify({"error": "Gemini quota exceeded. Check billing/quota and retry later."}), 429
        if e.kind in {"network", "timeout"}:
            return jsonify({"error": "Gemini service unreachable. Please retry."}), 503
        if e.kind == "model_not_found":
            return jsonify({"error": "Configured Gemini model is unavailable. Set GEMINI_MODEL in .env."}), 400
        return jsonify({"error": str(e)}), 502

    if not questions:
        logger.error("No questions generated for role=%s", role)
        return jsonify({"error": "No questions generated. Please retry."}), 502
    session_id = str(uuid.uuid4())
    s = Session(id=session_id, role=role, created_at=utc_now_iso(), questions=questions, current_index=0)
    SESSIONS[session_id] = s

    return jsonify(
        {
            "session_id": s.id,
            "role": s.role,
            "created_at": s.created_at,
            "question_count": len(s.questions),
            "current_index": s.current_index,
            "current_question": s.questions[0],
            "gemini_enabled": gemini.enabled(),
        }
    )


@app.post("/api/session/next")
def next_step():
    payload = request.get_json(silent=True) or {}
    session_id = (payload.get("session_id") or "").strip()
    answer = (payload.get("answer") or "").strip()
    proctoring = payload.get("proctoring") or {}
    images_b64 = payload.get("images_b64") or []
    if not isinstance(images_b64, list):
        images_b64 = []

    if not session_id or session_id not in SESSIONS:
        return _bad_request("Invalid session_id.", 404)

    s = SESSIONS[session_id]
    if s.current_index >= len(s.questions):
        return jsonify({"done": True})

    s.proctoring["tab_switches"] = int(proctoring.get("tab_switches") or s.proctoring.get("tab_switches") or 0)

    q = s.questions[s.current_index]
    try:
        evaluation = evaluator.evaluate(role=s.role, question=q["question"], answer=answer, images_b64=images_b64)
    except GeminiAPIError as e:
        logger.exception("Gemini evaluation failed")
        if e.kind == "invalid_api_key":
            return jsonify({"error": "Gemini API key is invalid. Update GEMINI_API_KEY in .env."}), 401
        if e.kind == "quota_exceeded":
            return jsonify({"error": "Gemini quota exceeded. Check billing/quota and retry later."}), 429
        if e.kind in {"network", "timeout"}:
            return jsonify({"error": "Gemini service unreachable. Please retry."}), 503
        return jsonify({"error": str(e)}), 502
    s.answers.append(
        {
            "index": s.current_index,
            "question": q,
            "answer": answer,
            "evaluation": evaluation,
        }
    )

    s.current_index += 1
    if s.current_index >= len(s.questions):
        return jsonify({"done": True, "session_id": s.id})

    return jsonify(
        {
            "done": False,
            "session_id": s.id,
            "current_index": s.current_index,
            "current_question": s.questions[s.current_index],
            "last_evaluation": evaluation,
        }
    )


@app.get("/api/session/<session_id>/report")
def report(session_id: str):
    session_id = (session_id or "").strip()
    if not session_id or session_id not in SESSIONS:
        return _bad_request("Invalid session_id.", 404)

    s = SESSIONS[session_id]
    total = len(s.answers)
    avg = round(sum(a["evaluation"]["score"] for a in s.answers) / total, 2) if total else 0.0
    max_score = total * 10
    total_score = sum(a["evaluation"]["score"] for a in s.answers)

    return jsonify(
        {
            "session_id": s.id,
            "role": s.role,
            "created_at": s.created_at,
            "finished_at": utc_now_iso(),
            "questions_total": len(s.questions),
            "answered": total,
            "total_score": total_score,
            "max_score": max_score,
            "average_score": avg,
            "proctoring": s.proctoring,
            "responses": s.answers,
        }
    )

HR_SECRET_TOKEN = os.environ.get("HR_SECRET_TOKEN", "super-secret-hr-token-123")

@app.get("/api/hr/resumes")
def list_resumes():
    token = request.headers.get("x-hr-token") or request.args.get("token")
    if token != HR_SECRET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
        
    upload_dir = os.path.join(_ROOT, "backend", "uploads", "resumes")
    if not os.path.exists(upload_dir):
        return jsonify({"resumes": []})
        
    resumes = os.listdir(upload_dir)
    return jsonify({"resumes": resumes})

@app.get("/api/hr/resumes/<path:filename>")
def download_resume(filename):
    token = request.headers.get("x-hr-token") or request.args.get("token")
    if token != HR_SECRET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
        
    upload_dir = os.path.join(_ROOT, "backend", "uploads", "resumes")
    return send_from_directory(upload_dir, filename)


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.post("/api/proctor/detect")
def proctor_detect():
    payload = request.get_json(silent=True) or {}
    image_b64 = payload.get("image_base64")
    conf = payload.get("conf", 0.35)
    if not image_b64:
        return _bad_request("Missing image_base64.")
    try:
        out = yolo.detect(image_b64=str(image_b64), conf=float(conf))
        return jsonify({"ok": True, **out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



@app.get("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:path>")
def serve_frontend_assets(path: str):
    return send_from_directory(FRONTEND_DIR, path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)





