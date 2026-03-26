import json
import re
from typing import Any

import requests
from dotenv import load_dotenv

from backend.utils import getenv_trimmed, safe_text

load_dotenv()


class GeminiAPIError(RuntimeError):
    def __init__(self, message: str, kind: str = "unknown", status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


def _strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


class GeminiService:
    """
    Role-based questions and evaluations via Google Gemini.
    Set GEMINI_API_KEY in the environment (e.g. .env). Never commit API keys.
    Optional: GEMINI_MODEL (default: gemini-1.5-flash).
    """

    def __init__(self) -> None:
        self.api_key = getenv_trimmed("GEMINI_API_KEY")
        self.model_name = getenv_trimmed("GEMINI_MODEL") or "gemini-1.5-flash-latest"
        self.timeout_sec = int(getenv_trimmed("GEMINI_TIMEOUT_SEC", "25") or "25")
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._resolved_model: str | None = None

    def _normalize_model_name(self, raw: str) -> str:
        name = (raw or "").strip()
        if name.startswith("models/"):
            return name.split("/", 1)[1]
        return name

    def _discover_model(self) -> str | None:
        if self._resolved_model:
            return self._resolved_model
        if not self.api_key:
            return None
        url = f"{self.base_url}/models"
        try:
            res = requests.get(url, params={"key": self.api_key}, timeout=self.timeout_sec)
            if not res.ok:
                return None
            data = res.json()
        except (requests.RequestException, ValueError):
            return None

        models = data.get("models", [])
        candidates: list[str] = []
        for m in models:
            if not isinstance(m, dict):
                continue
            methods = m.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            name = self._normalize_model_name(str(m.get("name", "")))
            if name:
                candidates.append(name)
        if not candidates:
            return None

        flash = [m for m in candidates if "flash" in m.lower()]
        chosen = (flash[0] if flash else candidates[0]).strip()
        self._resolved_model = chosen
        return chosen

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _generate(self, prompt: str, images_b64: list[str] = None) -> str:
        if not self.enabled():
            return ""

        requested_model = self._normalize_model_name(self._resolved_model or self.model_name)
        url = f"{self.base_url}/models/{requested_model}:generateContent"
        params = {"key": self.api_key}
        
        parts = []
        if images_b64:
            for img in images_b64:
                img_data = img
                if img.startswith("data:image"):
                    img_data = img.split(",", 1)[1]
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img_data
                    }
                })
        parts.append({"text": prompt})
        
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0.65,
                "responseMimeType": "application/json",
            },
        }
        headers = {"Content-Type": "application/json"}

        try:
            res = requests.post(url, params=params, headers=headers, json=payload, timeout=self.timeout_sec)
        except requests.Timeout as e:
            raise GeminiAPIError("Gemini request timed out.", kind="timeout") from e
        except requests.RequestException as e:
            raise GeminiAPIError(f"Gemini network error: {e}", kind="network") from e

        if not res.ok:
            err_msg = f"Gemini request failed with status {res.status_code}."
            kind = "api_error"
            try:
                data = res.json()
                api_error = data.get("error", {})
                api_msg = api_error.get("message")
                status_text = str(api_error.get("status", "")).upper()
                if api_msg:
                    err_msg = f"Gemini API error: {api_msg}"
                if res.status_code == 401:
                    kind = "invalid_api_key"
                elif res.status_code == 403 and ("QUOTA" in status_text or "quota" in err_msg.lower()):
                    kind = "quota_exceeded"
                elif res.status_code == 404:
                    kind = "model_not_found"
            except ValueError:
                pass
            if kind == "model_not_found":
                discovered = self._discover_model()
                if discovered and discovered != requested_model:
                    self._resolved_model = discovered
                    return self._generate(prompt, images_b64=images_b64)
            raise GeminiAPIError(err_msg, kind=kind, status_code=res.status_code)

        try:
            data = res.json()
        except ValueError as e:
            raise GeminiAPIError("Gemini returned non-JSON response.", kind="invalid_response") from e

        try:
            candidates = data.get("candidates", [])
            parts = candidates[0]["content"]["parts"]
            return "".join((p.get("text") or "") for p in parts).strip()
        except (IndexError, KeyError, TypeError) as e:
            raise GeminiAPIError("Gemini returned unexpected response format.", kind="invalid_response") from e

    def generate_questions(self, role: str, count: int, resume_text: str = "") -> list[dict[str, Any]]:
        """
        Returns a list of:
          { "question": str, "difficulty": "easy"|"medium"|"hard", "category": str }
        """
        raw_role = (role or "").strip()
        role = safe_text(raw_role, 100)
        count = int(count)

        role_norm = role.lower()
        if role_norm in {"hr", "human resources", "human-resource", "human-resources"}:
            return self._generate_hr_flow_questions(count=count, resume_text=resume_text)

        if not self.enabled():
            return self._fallback_questions(role, count)

        prompt = f"""You are an expert technical interviewer.
Generate exactly {count} distinct interview questions for this job role: {role}.

Requirements:
- Mix technical depth, practical scenarios, and communication / clarity.
- Difficulty should vary across easy, medium, and hard.
- Categories should be specific (e.g. python, sql, system-design, security, ml, devops) — not generic labels like "general".
- Each question must be self-contained and suitable for a live interview.

Return ONLY valid JSON with this exact shape (no markdown, no commentary):
{{"questions":[{{"question":"...","difficulty":"easy|medium|hard","category":"..."}}]}}
"""
        raw = self._generate(prompt)
        parsed = self._parse_questions_json(raw, role, count)
        if parsed is not None:
            return parsed

        raise GeminiAPIError("Gemini returned malformed question JSON. Please retry.", kind="invalid_response")

    def _generate_hr_flow_questions(self, count: int, resume_text: str) -> list[dict[str, Any]]:
        base_flow: list[dict[str, Any]] = [
            # 1) Warm-up Phase
            {"question": "Tell me about yourself.", "difficulty": "easy", "category": "Warm-up"},
            {"question": "Where are you from?", "difficulty": "easy", "category": "Warm-up"},
            {"question": "Briefly introduce your background.", "difficulty": "easy", "category": "Warm-up"},

            # 2) Education & Background
            {"question": "Tell me about your degree.", "difficulty": "easy", "category": "Education"},
            {"question": "Why did you choose this field?", "difficulty": "medium", "category": "Education"},
            {"question": "What did you learn during your studies?", "difficulty": "medium", "category": "Education"},

            # 3) Project Discussion (core HR + technical mix)
            {"question": "Explain your project.", "difficulty": "medium", "category": "Project (Technical)"},
            {"question": "What technologies did you use?", "difficulty": "medium", "category": "Project (Technical)"},
            {"question": "What challenges did you face?", "difficulty": "hard", "category": "Project (Technical)"},
            {"question": "What is your role in the project?", "difficulty": "medium", "category": "Project (Technical)"},
            {"question": "How is your project useful in the real world?", "difficulty": "medium", "category": "Project (Technical)"},

            # 4) Strengths & Weaknesses
            {"question": "What are your strengths?", "difficulty": "easy", "category": "Self-awareness"},
            {"question": "What is your biggest weakness?", "difficulty": "medium", "category": "Self-awareness"},

            # 5) Behavioral Questions
            {"question": "Tell me about a challenge you faced.", "difficulty": "medium", "category": "Behavioral"},
            {"question": "How do you handle pressure?", "difficulty": "medium", "category": "Behavioral"},
            {"question": "Describe a failure and what you learned.", "difficulty": "hard", "category": "Behavioral"},

            # 6) Career & Company Fit
            {"question": "Why should we hire you?", "difficulty": "medium", "category": "Career fit"},
            {"question": "Why do you want this job?", "difficulty": "easy", "category": "Career fit"},
            {"question": "Where do you see yourself in 5 years?", "difficulty": "medium", "category": "Career fit"},

            # 7) Closing Question
            {"question": "Do you have any questions for us?", "difficulty": "easy", "category": "Closing"},
        ]

        base_slice = base_flow[:count]
        # Keep the closing question ("Do you have any questions for us?") when there's enough room
        # for the main sections. This makes the HR flow feel complete even with lower counts.
        if count >= 8 and count < len(base_flow):
            base_slice[-1] = base_flow[-1]

        resume_text = safe_text(resume_text or "", 2000)
        if not resume_text or not self.enabled():
            # If Gemini isn't enabled or resume isn't provided, keep the deterministic HR flow.
            return [
                {
                    "question": safe_text(q["question"], 800),
                    "difficulty": safe_text(q["difficulty"], 20).lower(),
                    "category": safe_text(q["category"], 60),
                }
                for q in base_slice
            ]

        # If Gemini is available, rewrite the first `count` HR questions using the resume context,
        # but keep the ordering and the provided difficulty/category labels.
        difficulty_category_hint = "\n".join(
            f"{i+1}. difficulty={q['difficulty']}, category={q['category']}, question={q['question']}"
            for i, q in enumerate(base_slice)
        )
        prompt = f"""You are rewriting HR interview questions for a candidate.
Use the candidate resume to tailor each question naturally, but keep:
- The SAME number of questions: {count}
- The SAME ordering as the base list
- The SAME difficulty and category labels for each item
- Return ONLY valid JSON

Candidate resume:
{resume_text}

Base list (difficulty/category must remain exactly as shown):
{difficulty_category_hint}

Return JSON only with this shape:
{{"questions":[{{"question":"...","difficulty":"easy|medium|hard","category":"..."}}]}}
No markdown.
"""
        raw = self._generate(prompt)
        parsed = self._parse_questions_json(raw, "HR", count)
        if parsed is not None:
            return parsed

        # Fallback to deterministic flow on any Gemini/JSON failure.
        return [
            {
                "question": safe_text(q["question"], 800),
                "difficulty": safe_text(q["difficulty"], 20).lower(),
                "category": safe_text(q["category"], 60),
            }
            for q in base_slice
        ]

    def _parse_questions_json(self, raw: str, role: str, count: int) -> list[dict[str, Any]] | None:
        text = _strip_json_fence(raw)
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None

        qs = data.get("questions")
        if not isinstance(qs, list):
            return None

        out: list[dict[str, Any]] = []
        for q in qs[:count]:
            if not isinstance(q, dict):
                continue
            out.append(
                {
                    "question": safe_text(str(q.get("question", "")), 800),
                    "difficulty": safe_text(str(q.get("difficulty", "medium")), 20).lower(),
                    "category": safe_text(str(q.get("category", "technical")), 60),
                }
            )
        if len(out) != count or any(not x["question"] for x in out):
            return None
        return out

    def evaluate_answer(self, role: str, question: str, answer: str, images_b64: list[str] = None) -> dict[str, Any]:
        """
        Returns:
          { "score": int 0-10, "feedback": str, "communication": str, "strengths": [str], "improvements": [str], "emotion": str, "sentiment_feedback": str }
        """
        role = safe_text(role, 100)
        question = safe_text(question, 800)
        answer = safe_text(answer, 4000)

        if not self.enabled():
            return self._fallback_evaluation(role, question, answer)

        prompt = f"""You are an AI interview evaluator for role: {role}.

Analyze the candidate's answer and provide output in the following structured format exactly as JSON.

Per-question breakdown
Question: {question}
Candidate answer: {answer}

Feedback:
- Explain what is correct
- Explain what is missing (depth, examples, concepts like mutability, performance, etc.)
- Mention if the second part of the question is unanswered

Communication:
- Evaluate clarity, length, and explanation quality

Emotion:
- Detect candidate emotion (e.g., Nervous, Confident, Neutral)

Suggestions:
- Give clear, actionable suggestions to improve the answer
- Mention what to add (examples, use-cases, comparisons, etc.)
- Keep it simple and practical

Solution:
- Provide a perfect, interview-ready answer
- Include definition, key differences, and when to use each
- Add examples if needed
- Keep it concise but complete

Instruction: Score from 0-10 on correctness, depth, clarity, structure, and relevance.
If images are provided, perform multimodal sentiment analysis on the candidate's body gestures, facial expressions, and the text transcribed from their voice. Identify their emotion and provide constructive emotional feedback.
Return ONLY valid JSON with this exact shape (no markdown). "sentiment_feedback" should include analysis of both text/voice and body gestures.
{{"score": <int 0-10>, "feedback": "...", "communication": "...", "emotion": "Confident|Neutral|Nervous|Frustrated|...", "suggestions": ["..."], "solution": "...", "sentiment_feedback": "..."}}
"""
        raw = self._generate(prompt, images_b64=images_b64)
        parsed = self._parse_evaluation_json(raw)
        if parsed is not None:
            return parsed

        raise GeminiAPIError("Gemini returned malformed evaluation JSON. Please retry.", kind="invalid_response")

    def _parse_evaluation_json(self, raw: str) -> dict[str, Any] | None:
        text = _strip_json_fence(raw)
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict):
            return None
        try:
            score = int(data.get("score", 0))
        except (TypeError, ValueError):
            return None
        score = 0 if score < 0 else 10 if score > 10 else score
        suggestions = data.get("suggestions") or []
        if not isinstance(suggestions, list):
            suggestions = [suggestions] if isinstance(suggestions, str) else []
        solution = safe_text(str(data.get("solution", "")), 4000)

        emotion = data.get("emotion", "Neutral")
        if not isinstance(emotion, str):
            emotion = "Neutral"
        emotion = safe_text(emotion, 40)

        return {
            "score": score,
            "feedback": safe_text(str(data.get("feedback", "")), 2000),
            "communication": safe_text(str(data.get("communication", "")), 2000),
            "suggestions": [safe_text(x, 200) for x in suggestions[:8] if isinstance(x, str) and x.strip()],
            "solution": solution,
            "emotion": emotion,
            "sentiment_feedback": safe_text(str(data.get("sentiment_feedback", "")), 2000),
        }

    def _fallback_questions(self, role: str, count: int) -> list[dict[str, Any]]:
        """Minimal offline placeholder when Gemini is unavailable — not a fixed question bank."""
        difficulties = ["easy", "medium", "hard"]
        categories = ["technical", "practical", "communication", "problem-solving", "tools", "architecture"]
        out: list[dict[str, Any]] = []
        for i in range(count):
            d = difficulties[i % len(difficulties)]
            c = categories[i % len(categories)]
            out.append(
                {
                    "question": safe_text(
                        f"[Offline mode] As a {role}, explain how you would approach a realistic task "
                        f"typical for this role (scenario {i + 1} of {count}). Include tools, trade-offs, and how you would verify quality.",
                        500,
                    ),
                    "difficulty": d,
                    "category": c,
                }
            )
        return out

    def _fallback_evaluation(self, role: str, question: str, answer: str) -> dict[str, Any]:
        role = role.lower().strip()
        a = (answer or "").strip()
        if not a:
            return {
                "score": 0,
                "feedback": "No answer provided. Try to respond with a clear structure: brief summary, key points, and a concrete example.",
                "communication": "Answer was empty; focus on clarity and completeness.",
                "suggestions": ["Provide an answer", "Use a structured response", "Add an example"],
                "solution": "A perfect answer would depend on the question asked.",
            }

        length = len(a)
        score = 4
        if length > 80:
            score += 2
        if length > 200:
            score += 1
        if any(word in a.lower() for word in ["example", "because", "trade-off", "however", "therefore"]):
            score += 1
        if "python" in role and any(w in a.lower() for w in ["time complexity", "big-o", "exception", "async", "thread", "process"]):
            score += 1
        if "data" in role and any(w in a.lower() for w in ["join", "null", "outlier", "distribution", "p-value", "variance"]):
            score += 1

        score = 10 if score > 10 else score
        improvements = []
        if length < 80:
            improvements.append("Add more detail (why + how).")
        improvements.append("Use a clear structure (1–2–3) and finish with a concise summary.")

        a_lower = a.lower()
        fillers = ["um", "uh", "like", "you know", "sort of"]
        nervous_hits = sum(1 for f in fillers if f in a_lower)
        emotion = "Nervous" if nervous_hits >= 1 else "Confident"

        return {
            "score": int(score),
            "feedback": "Good start. Add more specificity and show your reasoning with one concrete example.",
            "communication": "Aim for a structured answer: context → approach → result.",
            "suggestions": improvements[:5],
            "solution": "A detailed model answer showing deeper technical understanding and structure.",
            "emotion": emotion,
        }
