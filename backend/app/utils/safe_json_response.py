"""JSONResponse that never emits NaN/Inf (RFC-compliant JSON)."""
from __future__ import annotations

import json
from typing import Any

from starlette.responses import JSONResponse

from app.utils.json_safe import sanitize_for_json


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            sanitize_for_json(content),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
