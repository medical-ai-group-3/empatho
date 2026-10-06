"""Common interface every segmentation backend (dummy or real ONNX) must satisfy."""
from abc import ABC, abstractmethod

import numpy as np


class SegmentationModel(ABC):
    name: str

    @abstractmethod
    def predict_logits(self, batch: np.ndarray) -> np.ndarray:
        raise NotImplementedError
