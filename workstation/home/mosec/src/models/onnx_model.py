from pathlib import Path

import numpy as np

from .base import SegmentationModel


class ONNXModel(SegmentationModel):
    def __init__(self, name: str, weight_path: str, use_gpu: bool = True):
        import onnxruntime as ort

        self.name = name
        self.weight_path = weight_path
        providers = ["CPUExecutionProvider"]
        if use_gpu:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(weight_path), providers=providers)
        self._input_name = self.session.get_inputs()[0].name
        self._output_name = self.session.get_outputs()[0].name

    @classmethod
    def weight_file(cls, model_dir: str, name: str) -> Path:
        return Path(model_dir) / f"{name}.onnx"

    @classmethod
    def is_available(cls, model_dir: str, name: str) -> bool:
        return cls.weight_file(model_dir, name).is_file()

    def predict_logits(self, batch: np.ndarray) -> np.ndarray:
        batch = np.ascontiguousarray(batch, dtype=np.float32)
        outputs = self.session.run([self._output_name], {self._input_name: batch})
        return outputs[0]
