"""Maria/Gemini voice output behind the V2's one TTSManager owner."""
from pathlib import Path
from collections import OrderedDict,deque
import base64,hashlib,json,os,tempfile,time,threading,urllib.request,wave
import pygame
import zuko_voice_config as settings
from movement_automation import MovementSelector
from vendor.nexus.voz import falar as legacy_speak
from zuko_local_tts import speak as local_speak

def maria_speak(texto,**options):
    if options.get('engine')=='windows':return local_speak(texto,**options)
    return legacy_speak(texto,**options)

_results=deque(maxlen=100);_lock=threading.RLock()
_audio_cache=OrderedDict();_audio_cache_bytes=0;_AUDIO_CACHE_LIMIT=16*1024*1024

def _cache_key(text,voice,style):
    raw=json.dumps([text,voice,style],ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()

def _cache_get(key):
    with _lock:
        audio=_audio_cache.get(key)
        if audio is not None:_audio_cache.move_to_end(key)
        return audio

def _cache_put(key,audio):
    global _audio_cache_bytes
    if len(audio)>_AUDIO_CACHE_LIMIT:return
    with _lock:
        previous=_audio_cache.pop(key,None)
        if previous is not None:_audio_cache_bytes-=len(previous)
        while _audio_cache and _audio_cache_bytes+len(audio)>_AUDIO_CACHE_LIMIT:
            _,discarded=_audio_cache.popitem(last=False);_audio_cache_bytes-=len(discarded)
        _audio_cache[key]=audio;_audio_cache_bytes+=len(audio)

def _maria_rate(config,text):
    base=int(config.get('windows_rate',2))
    emotion=MovementSelector.emotion_for(text)
    adjustment={'joy':1,'gratitude':1,'surprise':1,'empathy':-1,'sadness':-1}.get(emotion,0)
    return max(-10,min(10,base+adjustment)),emotion,MovementSelector.intent_for(text)

def _expressive_style(base,emotion,intent):
    expressions={'joy':'alegre e caloroso','gratitude':'grato e acolhedor','surprise':'surpreso e curioso',
        'empathy':'acolhedor e cuidadoso','sadness':'suave e empático','frustration':'calmo e respeitoso','calm':'natural e atento'}
    intentions={'greeting':'dê boas-vindas','celebration':'celebre com energia leve','affirmation':'demonstre concordância',
        'disagreement':'expresse discordância com respeito','support':'ofereça apoio','question':'soe curioso','comment':'converse naturalmente'}
    return (str(base or settings.DEFAULT['style']).strip()+'; expressão local: '+expressions.get(emotion,'natural e atento')+
            '; intenção: '+intentions.get(intent,'converse naturalmente')+'.')

def results():
    with _lock:return list(_results)

def _gemini(text,voice,style,path,cancel):
    if cancel():raise InterruptedError('cancelled')
    if not settings.authorization_status()['authorized']:
        raise PermissionError('Gemini selecionado — uso ao vivo não autorizado ou limite esgotado')
    key=_cache_key(text,voice,style)
    cached=_cache_get(key)
    if cached is not None:
        path.write_bytes(cached)
        return 0.0,True
    settings.consume();started=time.monotonic()
    payload={'model':settings.MODEL,'input':[{'type':'user_input','content':[{'type':'text','text':text,'annotations':[{'type':'speech_metadata','style':style}]}]}],
      'response_format':{'type':'audio','mime_type':'audio/wav'},'generation_config':{'speech_config':[{'voice':voice}]}}
    req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/interactions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
    with urllib.request.urlopen(req,timeout=35) as response:body=json.load(response)
    if cancel():raise InterruptedError('cancelled')
    blocks=[]
    for step in body.get('steps',[]):
        if step.get('type')=='model_output':blocks.extend(x for x in step.get('content',[]) if x.get('type')=='audio' and x.get('data'))
    if not blocks:raise RuntimeError('Gemini não retornou áudio')
    raw=base64.b64decode(blocks[-1]['data'],validate=True)
    if not raw.startswith(b'RIFF'):raise RuntimeError('Gemini retornou formato inesperado')
    path.write_bytes(raw);_cache_put(key,raw);return (time.monotonic()-started)*1000,False

def falar(texto,cancelar=lambda:False,*,on_synthesized=None,voice_config=None,voice_request=None,preview_audio_path=None,
          before_playback=None,on_playback_started=None,**legacy):
    def prepare_playback():
        if before_playback:before_playback()
        if cancelar():raise InterruptedError('cancelled before playback')
    if voice_config is None and not preview_audio_path:
        def synthesized_local():
            if on_synthesized:on_synthesized()
            prepare_playback()
        return maria_speak(texto,cancelar=cancelar,on_synthesized=synthesized_local,
                           on_playback_started=on_playback_started,**legacy)
    config=voice_config or settings.DEFAULT;start=time.monotonic();generated=None;fallback='';actual=config.get('engine','Microsoft Maria');
    maria_rate,emotion,intent=_maria_rate(config,texto)
    temporary=Path(__file__).resolve().parents[1]/'runtime/voice'
    temporary.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='zuko-v2-voice-',suffix='.wav',dir=temporary);os.close(fd);audio=Path(name);loaded=False
    row={'id':voice_request or '', 'engine':actual,'voice':config.get('voice') or 'Microsoft Maria',
         'emotion':emotion,'intent':intent,'status':'cancelled','tts_ms':None,'playback_start_ms':None,'total_ms':None,'fallback':''}
    try:
        if cancelar():return
        if preview_audio_path:
            audio=Path(preview_audio_path);row['engine']='arquivo de pré-escuta';generated=None
        elif actual=='Gemini TTS':
            try:
                style=_expressive_style(config.get('style',settings.DEFAULT['style']),emotion,intent)
                generated,cache_hit=_gemini(texto,config['voice'],style,audio,cancelar)
                row['cache_hit']=cache_hit
                if cache_hit:settings.record_cache_hit()
            except InterruptedError:raise
            except Exception as error:
                if isinstance(error,PermissionError):fallback='Uso ao vivo não autorizado ou limite de chamadas esgotado'
                elif isinstance(error,RuntimeError) and 'GEMINI_API_KEY' in str(error):fallback='Chave Gemini não disponível; fallback local'
                else:fallback='Gemini indisponível; fallback local ('+type(error).__name__+')'
                settings.record_fallback(fallback)
                row['fallback']=fallback;row['engine']='Microsoft Maria (fallback)';row['voice']='Microsoft Maria'
                if cancelar():return
                config={'windows_rate':maria_rate}
                # Preserve the installed local Windows Maria and the established playback code.
                def synthesized():
                    nonlocal generated
                    generated=(time.monotonic()-start)*1000
                    row['tts_ms']=generated
                    if on_synthesized:on_synthesized()
                    prepare_playback()
                result=maria_speak(texto,cancelar=cancelar,engine='windows',windows_rate=maria_rate,
                    on_synthesized=synthesized,on_playback_started=on_playback_started)
                row['status']='cancelled' if cancelar() else 'played'
                return result
        else:
            row['engine']='Microsoft Maria (local)'
            def synthesized():
                nonlocal generated
                generated=(time.monotonic()-start)*1000
                row['tts_ms']=generated
                if on_synthesized:on_synthesized()
                prepare_playback()
            result=maria_speak(texto,cancelar=cancelar,engine='windows',windows_rate=maria_rate,
                on_synthesized=synthesized,on_playback_started=on_playback_started)
            row['status']='cancelled' if cancelar() else 'played'
            return result
        if generated is not None:row['tts_ms']=generated
        elif preview_audio_path:row['tts_ms']=0
        with wave.open(str(audio),'rb') as wav:row['audio_seconds']=wav.getnframes()/wav.getframerate()
        if on_synthesized:on_synthesized()
        if not pygame.mixer.get_init():pygame.mixer.init()
        pygame.mixer.music.load(str(audio));loaded=True
        pygame.mixer.music.set_volume(float(config.get('volume',100))/100)
        if cancelar():return
        prepare_playback()
        pygame.mixer.music.play()
        row['playback_start_ms']=(time.monotonic()-start)*1000
        if not pygame.mixer.music.get_busy():raise RuntimeError('A reprodução não iniciou')
        if on_playback_started:on_playback_started()
        row['status']='played'
        while pygame.mixer.music.get_busy():
            if cancelar():pygame.mixer.music.stop();row['status']='cancelled';break
            pygame.time.wait(35)
    except InterruptedError:
        row['status']='cancelled'
        if not cancelar():raise
    except Exception as error:
        row['status']='error'
        row['error']=('Falha no sintetizador local Microsoft Maria ('+type(error).__name__+')' if row['engine'].startswith('Microsoft Maria')
                      else 'Falha na geração ou reprodução de voz ('+type(error).__name__+')')
        if row.get('fallback'):row['fallback_error']=row['error']
        raise
    finally:
        if cancelar() and row['status']!='error':row['status']='cancelled'
        if loaded:
            pygame.mixer.music.stop();pygame.mixer.music.unload()
        if not preview_audio_path:audio.unlink(missing_ok=True)
        row['total_ms']=(time.monotonic()-start)*1000
        with _lock:_results.append(row)
