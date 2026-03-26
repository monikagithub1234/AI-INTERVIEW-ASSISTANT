import base64
import io
from typing import Any

from PIL import Image


class YoloService:
    """
    YOLOv8 service (Ultralytics).
    Lazily loads model the first time it is used.
    """

    def __init__(self) -> None:
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from ultralytics import YOLO

        # Small, fast default model. Replace with yolov8s.pt for higher accuracy.
        self._model = YOLO("yolov8n.pt")
        return self._model

    @staticmethod
    def _decode_image_base64(data_url_or_b64: str) -> Image.Image:
        s = (data_url_or_b64 or "").strip()
        if "," in s and s.lower().startswith("data:"):
            s = s.split(",", 1)[1]
        raw = base64.b64decode(s)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def detect(self, image_b64: str, conf: float = 0.35) -> dict[str, Any]:
        model = self._ensure_model()
        img = self._decode_image_base64(image_b64)

        results = model.predict(img, conf=float(conf), verbose=False)
        r0 = results[0]

        names = r0.names or {}
        dets: list[dict[str, Any]] = []
        counts: dict[str, int] = {}

        if r0.boxes is not None:
            for b in r0.boxes:
                cls_id = int(b.cls.item())
                name = str(names.get(cls_id, cls_id))
                conf_v = float(b.conf.item())
                xyxy = [float(x) for x in b.xyxy[0].tolist()]
                dets.append({"name": name, "conf": round(conf_v, 3), "box": xyxy})
                counts[name] = counts.get(name, 0) + 1

        dets.sort(key=lambda d: d["conf"], reverse=True)

        return {
            "detections": dets[:15],
            "counts": counts,
        }

