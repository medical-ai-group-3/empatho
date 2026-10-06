import time

import numpy as np

from .base import SegmentationModel

SIMULATED_CALL_OVERHEAD_S = 0.05


class DummyUNet(SegmentationModel):
    def __init__(self, name: str, num_classes: int, seed: int = 0, simulated_overhead_s: float = SIMULATED_CALL_OVERHEAD_S):
        self.name = name
        self.num_classes = num_classes
        self._rng = np.random.default_rng(seed)
        self._simulated_overhead_s = simulated_overhead_s

    def predict_logits(self, batch: np.ndarray) -> np.ndarray:
        if self._simulated_overhead_s:
            time.sleep(self._simulated_overhead_s)
        n, _, h, w = batch.shape
        content_seed = int(abs(hash(batch[0].sum())) % (2**32 - 1))
        struct_rng = np.random.default_rng(content_seed)
        yy, xx = np.meshgrid(np.linspace(0, 1, h), np.linspace(0, 1, w), indexing="ij")
        centers = struct_rng.uniform(0.2, 0.8, size=(self.num_classes, 2))
        base_logits = np.zeros((self.num_classes, h, w), dtype=np.float32)
        for c in range(self.num_classes):
            cy, cx = centers[c]
            dist = (yy - cy) ** 2 + (xx - cx) ** 2
            base_logits[c] = -dist * 4.0
        noise = self._rng.normal(loc=0.0, scale=0.5, size=(n, self.num_classes, h, w)).astype(np.float32)
        return base_logits[np.newaxis, ...] + noise
