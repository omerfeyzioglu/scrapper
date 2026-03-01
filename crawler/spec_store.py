"""
spec_store.py — per-domain, per-path-prefix spec persistence.

Disk format: spec_cache/<domain>.json
{
  "domain": "<domain>",
  "specs": {
    "":         { <spec> },   # root pages (first path segment = "")
    "eskiler":  { <spec> },   # /eskiler/* pages
    "ilanlar":  { <spec> },   # /ilanlar/* pages
    ...
  }
}

Backward-compat: old single-spec files (no "specs" key) are migrated
automatically to {"": <old_spec>} on first read.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

CACHE_DIR = Path("spec_cache")


def _cache_path(domain: str) -> Path:
    safe = domain.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


# ------------------------------------------------------------------ low-level

def _load_raw(domain: str) -> dict:
    """Load the full cache file for domain; return {} on miss/error."""
    path = _cache_path(domain)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Backward-compat: old format has no "specs" key
        if "specs" not in data:
            log.info("Migrating old single-spec format for %s → prefix=''", domain)
            return {"domain": domain, "specs": {"": data}}
        return data
    except Exception as exc:
        log.warning("Could not read spec cache for %s: %s", domain, exc)
        return {}


def _save_raw(domain: str, data: dict) -> None:
    """Persist the full cache dict for domain."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(domain)
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        log.info("Saved spec cache for %s → %s", domain, path)
    except Exception as exc:
        log.warning("Could not save spec cache for %s: %s", domain, exc)


# ------------------------------------------------------------------ public API

def load_spec(domain: str, prefix: str) -> Optional[dict]:
    """Return the spec for (domain, prefix), or None if not cached."""
    data = _load_raw(domain)
    spec = data.get("specs", {}).get(prefix)
    if spec is not None:
        log.info("Loaded cached spec for %s [prefix=%r]", domain, prefix)
    return spec


def save_spec(domain: str, prefix: str, spec: dict) -> None:
    """Persist spec under (domain, prefix); keeps all other prefixes intact."""
    data = _load_raw(domain)
    if "specs" not in data:
        data = {"domain": domain, "specs": {}}
    data["specs"][prefix] = spec
    _save_raw(domain, data)
    log.info("Saved spec for %s [prefix=%r]", domain, prefix)


def all_specs(domain: str) -> dict[str, dict]:
    """Return {prefix: spec} mapping for domain (empty dict if nothing cached)."""
    data = _load_raw(domain)
    return data.get("specs", {})
