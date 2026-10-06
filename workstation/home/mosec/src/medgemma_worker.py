"""MedGemma 판독 보고서 생성 워커.

역할: 워커(cdss-worker)가 보낸 프롬프트와 이미지를 받아 MedGemma로 판독문을
생성해 생성 텍스트 그대로 돌려준다.

⚠️ 프롬프트를 이 파일에서 만들지 않는다. system/text 모두 호출자가 완성해서 보낸다.

Client contract (msgpack request body):
    {"job_id": "<uuid>", "system": "<시스템 프롬프트>", "text": "<사용자 프롬프트>",
     "image": <png bytes>, "max_new_tokens": 500}
Response (msgpack body):
    {"job_id": ..., "generated_text": "<모델이 생성한 원문>"}
"""
import io
import os
from typing import List, Union

from mosec import Worker, get_logger
from mosec.errors import ValidationError
from mosec.mixin import MsgpackMixin
from PIL import Image

logger = get_logger()

MODEL_ID = os.environ.get("MEDGEMMA_MODEL_ID", "google/medgemma-4b-it")
MAX_NEW_TOKENS_CAP = int(os.environ.get("MEDGEMMA_MAX_NEW_TOKENS_CAP", "800"))
DEFAULT_MAX_NEW_TOKENS = 500
LOAD_IN_8BIT = os.environ.get("MEDGEMMA_LOAD_IN_8BIT", "0") == "1"


class MedGemmaReport(MsgpackMixin, Worker):
    """GPU stage: 프롬프트 + 이미지 -> 판독문 생성."""

    def __init__(self):
        super().__init__()
        import torch
        from transformers import pipeline

        model_kwargs = {"torch_dtype": torch.bfloat16}
        if LOAD_IN_8BIT:
            from transformers import BitsAndBytesConfig

            model_kwargs = {"quantization_config": BitsAndBytesConfig(load_in_8bit=True)}
            logger.warning("[MedGemma] 8bit 양자화 활성")

        self.pipe = pipeline(
            "image-text-to-text",
            model=MODEL_ID,
            model_kwargs=model_kwargs,
            device_map="auto",
        )
        logger.info(f"[MedGemma] loaded {MODEL_ID} (8bit={LOAD_IN_8BIT})")

    @staticmethod
    def _validate(item: dict) -> dict:
        if not isinstance(item, dict):
            raise ValidationError(f"expected a msgpack map, got {type(item)}")
        for field in ("job_id", "system", "text", "image"):
            if field not in item:
                raise ValidationError(f"missing required field: {field}")

        try:
            image = Image.open(io.BytesIO(item["image"])).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"could not decode image: {exc}") from exc

        requested = int(item.get("max_new_tokens") or DEFAULT_MAX_NEW_TOKENS)
        return {
            "job_id": item["job_id"],
            "system": item["system"],
            "text": item["text"],
            "image": image,
            "max_new_tokens": min(requested, MAX_NEW_TOKENS_CAP),
        }

    def _generate(self, req: dict) -> str:
        messages = [
            {"role": "system", "content": [{"type": "text", "text": req["system"]}]},
            {"role": "user", "content": [
                {"type": "text", "text": req["text"]},
                {"type": "image", "image": req["image"]},
            ]},
        ]
        result = self.pipe(text=messages, max_new_tokens=req["max_new_tokens"])
        return result[0]["generated_text"][-1]["content"]

    def forward(self, data: Union[dict, List[dict]]):
        items = data if isinstance(data, list) else [data]
        results = []
        for item in items:
            req = self._validate(item)
            results.append({
                "job_id": req["job_id"],
                "generated_text": self._generate(req),
            })
        return results if isinstance(data, list) else results[0]
