#!/usr/bin/env python3
"""secrets.py - Secrets loader for devkit
========================================================================================

Parses config/secrets.env into os.environ. Call load() once at startup.
Use require() to fetch a value with a clear, actionable error on missing keys.

Author: Juan Garcia (arpatek)
"""

__version__ = "1.0.0"

# ──[ Imports ]─────────────────────────────────────────────────────────────────────────
import os
from pathlib import Path
from typing import Optional

# ──[ Config ]──────────────────────────────────────────────────────────────────────────

_DEVKIT_ROOT = Path(os.environ.get("DEVKIT_ROOT") or Path(__file__).resolve().parent.parent)
_SECRETS_FILE = _DEVKIT_ROOT / "config" / "secrets.env"

# ──[ Loader ]──────────────────────────────────────────────────────────────────────────


def load(path: Optional[Path] = None) -> None:
    """Parse secrets.env and inject keys into os.environ.

    Skips blank lines and comments. Does not override already-set env vars,
    so real env vars always win over the file.
    """
    p = path or _SECRETS_FILE
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')):
            value = value.strip("'\"")
        elif "#" in value:
            value = value.split("#")[0].strip()
        if key:
            os.environ.setdefault(key, value)


def require(key: str) -> str:
    """Return os.environ[key] or raise with a clear message pointing to the fix."""
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(
            f"Missing required config: {key}\n"
            f"  Add it to {_SECRETS_FILE}\n"
            f"  (copy config/secrets.env.example if the file does not exist)"
        )
    return val
