import os
import sys
from typing import List, Union

from mosec import Server, Worker, get_logger
from mosec.errors import ValidationError
from mosec.mixin import MsgpackMixin

from . import config
from .inference import (
    consensus_mask,
    decode_and_stain_normalize,
    download_gcs_bytes,
    pack_masks,
    render_mask_png,
    run_mc_dropout_tiled,
    upload_gcs_bytes,
)
from .model_registry import ModelRegistry

logger = get_logger()


class Preprocess(MsgpackMixin, Worker):
    def forward(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValidationError(f"expected a msgpack map, got {type(data)}")
        for field in ("job_id", "gcs_image_path"):
            if field not in data:
                raise ValidationError(f"missing required field: {field}")
        try:
            image_bytes = download_gcs_bytes(data["gcs_image_path"])
        except Exception as exc:
            raise ValidationError(f"GCS에서 이미지를 읽지 못함: {exc}") from exc
        try:
            raw_hwc, rgb_hwc = decode_and_stain_normalize(image_bytes)
        except Exception as exc:
            raise ValidationError(f"could not decode image: {exc}") from exc
        return {
            "job_id": data["job_id"],
            "model_name": data.get("model_name", "unet_v1"),
            "rgb_hwc": rgb_hwc,
            "raw_hwc": raw_hwc,
            # 마스크를 같은 버킷에 업로드하려고 Inference 단계까지 전달한다
            # (2026-08-05, 프론트엔드 오버레이용 마스크 이미지 기능 추가).
            "gcs_image_path": data["gcs_image_path"],
        }


class Inference(MsgpackMixin, Worker):
    def __init__(self):
        super().__init__()
        self.registry = ModelRegistry()
        logger.info(f"[Inference] models registered: {self.registry.registered_names()}")

    def _upload_mask(self, item: dict, masks) -> "str | None":
        """다수결 마스크를 색칠된 PNG로 만들어 같은 버킷의 masks/{job_id}.png에
        올린다. 업로드가 실패해도 세그멘테이션 자체는 정상 진행되도록 여기서
        예외를 삼키고 None을 돌려준다 (호출부 참고)."""
        try:
            bucket_name = item["gcs_image_path"][len("gs://"):].split("/", 1)[0]
            mask_key = f"masks/{item['job_id']}.png"
            png_bytes = render_mask_png(consensus_mask(masks))
            upload_gcs_bytes(f"gs://{bucket_name}/{mask_key}", png_bytes)
            return mask_key
        except Exception as exc:  # noqa: BLE001 — 업로드 실패는 치명적이지 않음
            logger.warning(f"[Inference] 마스크 업로드 실패 (세그멘테이션은 계속 진행): {exc}")
            return None

    def forward(self, data: Union[dict, List[dict]]):
        items = data if isinstance(data, list) else [data]
        results = []
        for item in items:
            model = self.registry.resolve(item["model_name"])
            rgb_hwc = item["rgb_hwc"]
            raw_hwc = item["raw_hwc"]
            try:
                masks = run_mc_dropout_tiled(model, rgb_hwc, raw_uint8_hwc=raw_hwc, n=config.MC_DROPOUT_N)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            _, h, w = masks.shape
            mask_key = self._upload_mask(item, masks)
            results.append(
                {
                    "job_id": item["job_id"],
                    "model_name_used": model.name,
                    "mc_samples": int(masks.shape[0]),
                    "height": h,
                    "width": w,
                    "num_classes": config.NUM_CLASSES,
                    "masks": pack_masks(masks),
                    "mask_key": mask_key,
                }
            )
        return results if isinstance(data, list) else results[0]


def build_server() -> Server:
    server = Server()
    server.append_worker(Preprocess, num=config.NUM_PREPROCESS_WORKERS)
    inference_env = [{"CUDA_VISIBLE_DEVICES": config.CUDA_VISIBLE_DEVICES}] * config.NUM_INFERENCE_WORKERS
    server.append_worker(
        Inference,
        num=config.NUM_INFERENCE_WORKERS,
        max_batch_size=config.MAX_BATCH_SIZE,
        max_wait_time=config.MAX_WAIT_TIME_MS,
        env=inference_env,
    )
    if config.ENABLE_MEDGEMMA:
        from .medgemma_worker import MedGemmaReport
        medgemma_env = [{"CUDA_VISIBLE_DEVICES": config.CUDA_VISIBLE_DEVICES}] * config.NUM_MEDGEMMA_WORKERS
        server.append_worker(
            MedGemmaReport,
            num=config.NUM_MEDGEMMA_WORKERS,
            route="/medgemma",
            env=medgemma_env,
        )
    return server


if __name__ == "__main__":
    port = os.environ.get("PORT", str(config.HTTP_PORT))
    if "--port" not in sys.argv:
        sys.argv += ["--port", port]
    build_server().run()
