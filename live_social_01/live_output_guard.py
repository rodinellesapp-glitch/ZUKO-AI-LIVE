"""Local speech-only parsing; no logging of raw output and no model retries."""
from dataclasses import dataclass
import re

OUTPUT_CONTRACT = """
CONTRATO DE SAÍDA
Sua saída será enviada diretamente para voz. Retorne SOMENTE a fala final do JARVIS.
Não escreva análise, raciocínio, intenção, contexto, plano, instruções, rótulos,
notas, metadados, 'JARVIS:', '(Análise Interna)', 'Resposta:' ou markdown técnico.
Comece diretamente pela frase que deve ser falada.
"""
GUARD_FALLBACK = "Deixa eu reformular isso de um jeito melhor."
EMPTY_FALLBACK = "Tive uma pequena instabilidade agora. Pode mandar de novo?"
_INTERNAL = re.compile(
    r"an[aá]lise\s+interna|chain\s+of\s+thought|(?:inten[cç][aã]o|contexto|refer[eê]ncia|"
    r"estado|continuidade|racioc[ií]nio|jarvis|resposta(?:\s+final)?|plano|metadados)\s*:|```|<think>", re.I)
_FINAL = re.compile(r"(?:^|\n)\s*(?:Resposta final|Fala final|JARVIS|Resposta)\s*:\s*", re.I)
_EMPTY_SOCIAL = re.compile(r"(?:opa|e a[ií](?:,? galera)?|legal|bacana|que massa|eita|boa)[!?.\s]*", re.I)

@dataclass(frozen=True)
class SpeechOutput:
    text: str
    category: str = "OK"
    finish_reason: str = "STOP"
    output_chars: int = 0

def guard_text(text: str) -> SpeechOutput:
    if _INTERNAL.search(text):
        matches = list(_FINAL.finditer(text))
        if matches:
            final = text[matches[-1].end():].strip()
            if final and not _INTERNAL.search(final) and not _EMPTY_SOCIAL.fullmatch(final):
                return SpeechOutput(final, "OUTPUT_GUARD_BLOCKED_EXTRACTED")
        return SpeechOutput(GUARD_FALLBACK, "OUTPUT_GUARD_BLOCKED")
    if _EMPTY_SOCIAL.fullmatch(text.strip()):
        return SpeechOutput(GUARD_FALLBACK, "OUTPUT_GUARD_BLOCKED_EMPTY_SOCIAL")
    return SpeechOutput(text.strip())

def _enum(value):
    return str(getattr(value, 'name', value) or '').split('.')[-1].upper()

def parse_speech(response) -> SpeechOutput:
    """Keep only safe, final speech while exposing non-sensitive finish metadata."""
    try:
        feedback = getattr(response, 'prompt_feedback', None)
        block = _enum(getattr(feedback, 'block_reason', None))
        if block not in ('', '0', 'BLOCKED_REASON_UNSPECIFIED'):
            return SpeechOutput(EMPTY_FALLBACK, 'CANDIDATE_BLOCKED', block, 0)
        candidates = getattr(response, 'candidates', None)
        finish = 'STOP'
        if candidates:
            candidate = candidates[0]
            finish = _enum(getattr(candidate, 'finish_reason', None))
            if finish in ('SAFETY', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII', 'RECITATION'):
                return SpeechOutput(EMPTY_FALLBACK, 'CANDIDATE_BLOCKED', finish, 0)
            if finish not in ('', 'STOP', 'FINISH_REASON_UNSPECIFIED'):
                category = 'UNUSUAL_FINISH_' + ('MAX_TOKENS' if finish == 'MAX_TOKENS' else 'OTHER')
                return SpeechOutput(EMPTY_FALLBACK, category, finish, 0)
            parts = getattr(getattr(candidate, 'content', None), 'parts', None) or []
            content = ''.join(part.text for part in parts
                              if not getattr(part, 'thought', False) and isinstance(getattr(part, 'text', None), str))
            if not content.strip():
                return SpeechOutput(EMPTY_FALLBACK, 'CANDIDATE_NO_TEXT', finish, 0)
        else:
            content = getattr(response, 'text', None)
        if not isinstance(content, str) or not content.strip():
            return SpeechOutput(EMPTY_FALLBACK, 'EMPTY_RESPONSE', finish, 0)
        guarded = guard_text(content)
        return SpeechOutput(guarded.text, guarded.category, finish, len(content))
    except Exception:
        return SpeechOutput(EMPTY_FALLBACK, 'PARSING_ERROR', 'PARSING_ERROR', 0)
