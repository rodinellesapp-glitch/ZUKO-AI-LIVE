"""V2 voice selection; Gemini usage requires an explicit, session-only grant."""
from pathlib import Path
import json, os, threading
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'zuko_voice_settings.json'
ASSETS=ROOT/'live_social_01/assets/voice_previews'
MODEL='gemini-3.8-flash-tts'
DEFAULT={'engine':'Microsoft Maria','voice':'','style':'Cartoon masculino jovem, engraçado e expressivo.'}
MIN_SESSION_CALLS=1
MAX_SESSION_CALLS=100
_lock=threading.RLock();_approved_calls=0;_authorized=False;_authorized_limit=0;_configured_limit=1;_calls_used=0
_session_id=None;_session_active=False;_fallback_count=0;_cache_hits=0;_last_fallback='';_fallback_reasons=Counter()

def load():
    with _lock:
        if not PATH.exists():return dict(DEFAULT)
        data=json.loads(PATH.read_text(encoding='utf-8'))
        stored=data.get('active',{})
        result={**DEFAULT,**{key:stored[key] for key in DEFAULT if key in stored}}
        if result['engine'] not in {'Microsoft Maria','Gemini TTS'}:return dict(DEFAULT)
        if result['engine']=='Gemini TTS' and result['voice'] not in {'Puck','Fenrir'}:return dict(DEFAULT)
        return result

def save(engine,voice,style=None):
    if engine not in {'Microsoft Maria','Gemini TTS'}:raise ValueError('Motor de voz inválido')
    if engine=='Gemini TTS' and voice not in {'Puck','Fenrir'}:raise ValueError('Selecione Puck ou Fenrir')
    value={'engine':engine,'voice':voice if engine=='Gemini TTS' else '', 'style':style or DEFAULT['style']}
    with _lock:
        baseline=load()
        data={'active':value,'previous':baseline}
        tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,PATH)
    return value

def restore_maria():return save('Microsoft Maria','')

def begin_session(session_id):
    global _approved_calls,_authorized,_authorized_limit,_calls_used,_session_id,_session_active
    global _fallback_count,_cache_hits,_last_fallback,_fallback_reasons
    with _lock:
        if _session_id!=session_id:
            _approved_calls=0;_authorized=False;_authorized_limit=_configured_limit;_calls_used=0
            _approved_calls=_configured_limit
            _fallback_count=0;_cache_hits=0;_last_fallback='';_fallback_reasons=Counter()
            _session_id=session_id
        _session_active=True
        return authorization_status()

def end_session(session_id):
    global _authorized,_session_active
    with _lock:
        if _session_id==session_id:
            _authorized=False;_session_active=False
        return authorization_status()

def configure_limit(calls):
    global _approved_calls,_authorized,_authorized_limit,_configured_limit
    if calls is not None and (type(calls) is not int or not MIN_SESSION_CALLS<=calls<=MAX_SESSION_CALLS):
        raise ValueError(f'Limite deve ser ILIMITADO ou um número inteiro entre {MIN_SESSION_CALLS} e {MAX_SESSION_CALLS}.')
    with _lock:
        _configured_limit=calls
        if not _session_active:_authorized_limit=calls
        if _session_active:
            _authorized_limit=calls
            _approved_calls=None if calls is None else max(0,calls-_calls_used)
            if _approved_calls==0:_authorized=False
        return authorization_status()

def approve(calls):
    global _approved_calls,_authorized,_authorized_limit,_configured_limit
    if calls is not None and (type(calls) is not int or not MIN_SESSION_CALLS<=calls<=MAX_SESSION_CALLS):
        raise ValueError(f'Limite deve ser ILIMITADO ou um número inteiro entre {MIN_SESSION_CALLS} e {MAX_SESSION_CALLS}.')
    with _lock:
        if not _session_active:raise PermissionError('Autorize Gemini TTS somente durante uma sessão TikTok Real ativa.')
        _configured_limit=calls;_authorized_limit=calls
        _approved_calls=None if calls is None else max(0,calls-_calls_used)
        if _approved_calls==0:
            _authorized=False
            raise PermissionError('Limite Gemini TTS desta sessão esgotado; a cota só reinicia em nova sessão TikTok Real.')
        _authorized=True
        return authorization_status()

def revoke():
    global _authorized
    with _lock:
        _authorized=False
        return authorization_status()

def authorization_status():
    with _lock:
        return {'authorized':_authorized and (_approved_calls is None or _approved_calls>0),'remaining':_approved_calls,
                'limit':_authorized_limit,'used':_calls_used,'session_active':_session_active,
                'fallbacks':_fallback_count,'cache_hits':_cache_hits,'last_fallback':_last_fallback,
                'fallback_reasons':dict(_fallback_reasons)}

def record_cache_hit():
    global _cache_hits
    with _lock:_cache_hits+=1

def record_fallback(reason):
    global _fallback_count,_last_fallback
    text=str(reason)[:120]
    folded=text.casefold()
    category=('AUTHORIZATION_OR_LIMIT' if any(word in folded for word in ('permission','authoriz','limit','cota')) else
              'TIMEOUT' if 'timeout' in folded or 'timed out' in folded else
              'PROVIDER_ERROR' if any(word in folded for word in ('api','http','network','connection','error')) else
              'OTHER')
    with _lock:
        _fallback_count+=1;_last_fallback=text;_fallback_reasons[category]+=1

def consume():
    global _approved_calls,_authorized,_calls_used
    with _lock:
        if not _session_active or not _authorized or _approved_calls==0:
            raise PermissionError('Gemini selecionado — uso ao vivo não autorizado ou limite esgotado')
        if not os.environ.get('GEMINI_API_KEY','').strip():raise RuntimeError('GEMINI_API_KEY não acessível; fallback Maria')
        if _approved_calls is not None:_approved_calls-=1
        _calls_used+=1
        if _approved_calls==0:_authorized=False

def remaining():
    with _lock:return _approved_calls

def estimate_short_batch(calls=10):
    # Standard published price through 2026-12-31. Estimate assumes <=10 sec/audio.
    return max(0,int(calls))*0.00225
