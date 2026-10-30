"""Local pytest can import app.main without skfolio metadata (65 pin stays in lock)."""
from __future__ import annotations

from importlib import metadata

_orig = metadata.version


def _version(name: str) -> str:
    try:
        return _orig(name)
    except metadata.PackageNotFoundError:
        if name == "skfolio":
            return "0.6.0"
        raise


metadata.version = _version


# Existing API tests mint tokens without the phone claim; the phone gate has
# its own tests (test_phone_signin.py) that switch it back on.
import os as _os

_os.environ.setdefault("PHONE_SIGNIN_REQUIRED", "false")
