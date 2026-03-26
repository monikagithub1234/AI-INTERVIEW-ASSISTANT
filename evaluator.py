from backend.gemini_service import GeminiService
from backend.utils import clamp_int, safe_text


class Evaluator:
    def __init__(self) -> None:
        self.gemini = GeminiService()

    def evaluate(self, role: str, question: str, answer: str, images_b64: list[str] = None) -> dict:
        role = safe_text(role, 100)
        question = safe_text(question, 800)
        answer = safe_text(answer, 4000)
        if images_b64 is None:
            images_b64 = []

        result = self.gemini.evaluate_answer(role=role, question=question, answer=answer, images_b64=images_b64)
        result["score"] = clamp_int(int(result.get("score", 0)), 0, 10)
        return result

