"""Persistent, non-secret Gemini session limits for the ZUKO V2 dashboard."""
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
LIMITS_PATH = ROOT / 'gemini_limits.json'
DEFAULT_LIMITS = {'gemini_text': 100, 'gemini_tts': 1}
MAX_LIMIT = 100
_VERSION = 1


def _validate_limit(value):
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= MAX_LIMIT:
        raise ValueError('Cada limite deve ser ILIMITADO ou um inteiro entre 1 e 100.')
    return value


def normalize_limits(values):
    if not isinstance(values, dict):
        raise ValueError('Configuração de limites inválida.')
    return {
        'gemini_text': _validate_limit(values['gemini_text']),
        'gemini_tts': _validate_limit(values['gemini_tts']),
    }


def load_limits(path=LIMITS_PATH):
    """Load saved caps; absent, malformed, or unsupported data falls back safely."""
    path = Path(path)
    if not path.is_file():
        return dict(DEFAULT_LIMITS)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != _VERSION:
            return dict(DEFAULT_LIMITS)
        return normalize_limits(data)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return dict(DEFAULT_LIMITS)


def save_limits(gemini_text, gemini_tts, path=LIMITS_PATH):
    """Atomically save only the two non-secret call limits."""
    values = normalize_limits({'gemini_text': gemini_text, 'gemini_tts': gemini_tts})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'version': _VERSION, **values}
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', newline='\n', dir=path.parent,
            prefix=f'.{path.name}.', suffix='.tmp', delete=False
        ) as temp_file:
            temp_name = temp_file.name
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write('\n')
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return values


def apply_limits(values, text_budget=None, tts_config=None, epoch=None):
    """Apply saved limits without resetting usage counters or granting authorization."""
    values = normalize_limits(values)
    if text_budget is not None:
        ok, reason = text_budget.set_limit(values['gemini_text'], epoch)
        if not ok:
            raise ValueError(f'Não foi possível aplicar o limite Gemini Text: {reason}.')
    if tts_config is not None:
        tts_config.configure_limit(values['gemini_tts'])
    return {
        'limits': values,
        'gemini_text': text_budget.snapshot(epoch) if text_budget is not None else None,
        'gemini_tts': tts_config.authorization_status() if tts_config is not None else None,
    }


def load_and_apply_limits(path=LIMITS_PATH, text_budget=None, tts_config=None, epoch=None):
    """Load persisted caps and apply them, used by the INICIAR LIVE action."""
    values = load_limits(path)
    states = apply_limits(values, text_budget, tts_config, epoch)
    return values, states
