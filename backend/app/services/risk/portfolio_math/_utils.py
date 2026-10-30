from __future__ import annotations

from typing import Sequence

import numpy as np


def as_float_array(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]
