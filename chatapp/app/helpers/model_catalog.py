"""Shared model catalog loader.

Reads the single source of truth at ``app/static/models.json`` (the same file the
browser uses via ``/static/models.json``) so model ids, display names, and
pricing are defined in exactly one place for both Python and JavaScript.

Consumers:
  * ``admin/cost_calculator.py`` — pricing (USD per 1M input/output tokens)
  * ``templates_config`` — injects the catalog as a template global so the
    front-end (``static/js/chat.js``) reads the very same data.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "static" / "models.json"

# Used when the catalog file is missing/unreadable so callers never crash.
_FALLBACK = {"default_model_id": "", "models": []}


@lru_cache(maxsize=None)
def load_catalog() -> dict:
    """Load the model catalog JSON. Never raises."""
    try:
        with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("models"), list):
            raise ValueError("models.json missing 'models' list")
        return data
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not load model catalog from %s: %s", _CATALOG_PATH, e)
        return _FALLBACK


def get_models() -> List[dict]:
    """List of model dicts: {id, name, input, output}."""
    return load_catalog().get("models", [])


def default_model_id() -> str:
    return load_catalog().get("default_model_id", "")


def get_pricing() -> Dict[str, Dict[str, float]]:
    """{model_id: {"input": rate, "output": rate}} per 1M tokens."""
    return {
        m["id"]: {"input": float(m.get("input", 0.0)), "output": float(m.get("output", 0.0))}
        for m in get_models()
        if m.get("id")
    }


def model_name(model_id: str) -> str:
    """Friendly display name for a model id (falls back to the raw id)."""
    for m in get_models():
        if m.get("id") == model_id:
            return m.get("name", model_id)
    return model_id


def get_model_api(model_id: str | None) -> str:
    """Get the API type for a model ('chat', 'responses', or 'messages').

    Returns 'chat' as default if model not found or api field missing.
    """
    if not model_id:
        return "chat"
    for m in get_models():
        if m.get("id") == model_id:
            return m.get("api", "chat")
    logger.warning("Unknown model_id %r — defaulting api to 'chat'", model_id)
    return "chat"
