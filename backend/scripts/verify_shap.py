#!/usr/bin/env python3
"""Production verification helper for SHAP + LightGBM."""
import math

import shap

from app.services.market_analysis.shap_explainer import (
    compute_shap_top_factors,
    features_from_prices_volumes,
)
from app.services.ml.model import get_classifier

classifier = get_classifier()
prices = [100.0 + math.sin(i / 10) * 2 + i * 0.05 for i in range(280)]
feat = features_from_prices_volumes(prices, [800_000.0] * 280)
factors, ok, gaps = compute_shap_top_factors(feat, top_n=3)

print("shap_version", shap.__version__)
print("model_loaded", classifier._model is not None)
print("shap_available", ok)
print("gaps", gaps)
for item in factors or []:
    print(f"factor {item.feature} {item.contribution:+.6f}")
