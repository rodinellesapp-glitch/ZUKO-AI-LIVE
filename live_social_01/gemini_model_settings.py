"""Persistent, allowlisted Gemini text model selection for ZUKO V4."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path


CATALOG = (
    ("Gemini 2.5 Flash-Lite", "gemini-2.5-flash-lite", "stable"),
    ("Gemini 2.5 Flash", "gemini-2.5-flash", "stable"),
    ("Gemini 3.6 Flash", "gemini-3.6-flash", "stable"),
    ("Gemini 3.8 Flash", "gemini-3.8-flash", "stable"),
    ("Gemini 3.1 Pro (prévia)", "gemini-3.1-pro-preview", "preview"),
)
MODEL_IDS = frozenset(model_id for _label, model_id, _stage in CATALOG)
LABEL_BY_ID = {model_id: label for label, model_id, _stage in CATALOG}
ID_BY_LABEL = {label: model_id for label, model_id, _stage in CATALOG}
PREFERRED_MODEL = "gemini-3.8-flash"
SETTINGS_PATH = Path(__file__).resolve().parents[1] / "gemini_model_settings.json"


def validate_model_id(model_id: str) -> str:
    value = str(model_id or "").strip()
    if value not in MODEL_IDS:
        raise ValueError("GEMINI_MODEL_UNSUPPORTED")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _default_state(default_model: str) -> dict[str, object]:
    current = default_model if default_model in MODEL_IDS else "gemini-2.5-flash-lite"
    return {
        "configured_model": current,
        "selected_model": PREFERRED_MODEL,
        "previous_model": current,
        "last_successful_model": None,
        "last_changed_at": None,
        "status": "AGUARDANDO_APLICACAO",
        "last_error": None,
        "settings_error": None,
    }


def load(default_model: str, *, path: Path | None = None) -> dict[str, object]:
    target = path or SETTINGS_PATH
    state = _default_state(default_model)
    if not target.exists():
        return state
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        configured = validate_model_id(data.get("configured_model"))
        selected = validate_model_id(data.get("selected_model", configured))
        previous = data.get("previous_model")
        successful = data.get("last_successful_model")
        if previous is not None:
            previous = validate_model_id(previous)
        if successful is not None:
            successful = validate_model_id(successful)
        state.update({
            "configured_model": configured,
            "selected_model": selected,
            "previous_model": previous or state["previous_model"],
            "last_successful_model": successful,
            "last_changed_at": data.get("last_changed_at"),
            "status": data.get("status", "AGUARDANDO_AUTORIZACAO"),
            "last_error": data.get("last_error"),
        })
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        state.update(status="ERRO_CONFIGURACAO", settings_error="GEMINI_MODEL_SETTINGS_INVALID")
    return state


def _write(state: dict[str, object], *, path: Path | None = None) -> dict[str, object]:
    target = path or SETTINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "provider": "gemini_api",
        "configured_model": validate_model_id(state["configured_model"]),
        "selected_model": validate_model_id(state["selected_model"]),
        "previous_model": (validate_model_id(state["previous_model"])
                           if state.get("previous_model") else None),
        "last_successful_model": (validate_model_id(state["last_successful_model"])
                                  if state.get("last_successful_model") else None),
        "last_changed_at": state.get("last_changed_at"),
        "status": str(state.get("status", "AGUARDANDO_AUTORIZACAO")),
        "last_error": state.get("last_error"),
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
    state.update(data)
    return dict(state)


def apply(model_id: str, state: dict[str, object], *, path: Path | None = None) -> dict[str, object]:
    selected = validate_model_id(model_id)
    previous = state.get("configured_model") or state.get("previous_model")
    updated = dict(state)
    updated.update({
        "configured_model": selected,
        "selected_model": selected,
        "previous_model": previous if previous in MODEL_IDS else None,
        "last_changed_at": _utc_now(),
        "status": "AGUARDANDO_AUTORIZACAO",
        "last_error": None,
        "settings_error": None,
    })
    return _write(updated, path=path)


def record_success(model_id: str, state: dict[str, object], *, path: Path | None = None) -> dict[str, object]:
    model_id = validate_model_id(model_id)
    updated = dict(state)
    updated.update(last_successful_model=model_id, status="PRONTO", last_error=None)
    return _write(updated, path=path)


def record_failure(model_id: str, error_code: str, state: dict[str, object], *,
                   rollback_model: str | None = None,
                   path: Path | None = None) -> dict[str, object]:
    model_id = validate_model_id(model_id)
    updated = dict(state)
    updated.update(status="ERRO", last_error={"model": model_id, "code": str(error_code)[:80]})
    if rollback_model is not None:
        rollback_model = validate_model_id(rollback_model)
        updated.update(configured_model=rollback_model, selected_model=rollback_model)
    return _write(updated, path=path)
