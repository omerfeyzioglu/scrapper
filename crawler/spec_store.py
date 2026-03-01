"""
spec_store.py — per-domain spec persistence in spec_cache/<domain>.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_DIR = Path("spec_cache")


def spec_path(domain: str) -> Path:
    """Return the path for a domain's spec file."""
    safe = domain.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def load_spec(domain: str) -> dict | None:
    """Load and return the spec for *domain*, or None if not cached."""
    path = spec_path(domain)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            spec = json.load(fh)
        log.info("Loaded cached spec for %s from %s", domain, path)
        return spec
    except Exception as exc:
        log.warning("Could not read spec cache %s: %s", path, exc)
        return None


def save_spec(domain: str, spec: dict) -> None:
    """Persist *spec* for *domain*; creates spec_cache/ if needed."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = spec_path(domain)
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=2)
        log.info("Saved spec for %s → %s", domain, path)
    except Exception as exc:
        log.warning("Could not save spec cache %s: %s", path, exc)
