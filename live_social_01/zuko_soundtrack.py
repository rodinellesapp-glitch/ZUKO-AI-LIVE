"""Local soundtrack with its own reserved mixer channel and playback ducking.

Does not touch pygame.mixer.music, Windows master volume, AI or broadcast tools.
"""
from collections import Counter, deque
from copy import deepcopy
from pathlib import Path
import json
import os
import random
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
SETTINGS_PATH=ROOT/'zuko_soundtrack_settings.json'
DEFAULT={'version':1,'normal_volume':35,'speech_volume':8,'duck_ms':300,
         'restore_ms':800,'hold_ms':350,'mute':False,'shuffle':False,'playlist':[]}


def local_audio_path(value, *, exists=True):
    text=str(value)
    if not text or len(text)>2048 or text.startswith(('\\\\','//')) or any(c in text for c in ('"','\r','\n','\x00')):
        raise ValueError('Use um arquivo local MP3 ou WAV.')
    path=Path(text)
    if not path.is_absolute() or path.suffix.lower() not in {'.mp3','.wav'}:
        raise ValueError('Use um caminho local absoluto MP3 ou WAV.')
    if exists and not path.is_file():raise ValueError('Arquivo de áudio não encontrado.')
    return str(path.resolve())


def validate_preferences(value):
    legacy_keys=set(DEFAULT)-{'shuffle'}
    if not isinstance(value,dict) or set(value) not in (legacy_keys,set(DEFAULT)) or value['version']!=1:
        raise ValueError('Preferências de trilha inválidas.')
    value={**value,'shuffle':value.get('shuffle',False)}
    if type(value['shuffle']) is not bool:raise ValueError('Modo aleatório inválido.')
    for key in ('normal_volume','speech_volume'):
        if type(value[key]) is not int or not 0<=value[key]<=100:raise ValueError('Volume deve estar entre 0 e 100%.')
    if value['speech_volume']>value['normal_volume']:raise ValueError('Volume durante a fala deve ser menor ou igual ao normal.')
    for key in ('duck_ms','restore_ms'):
        if type(value[key]) is not int or not 0<=value[key]<=5000:raise ValueError('Transição deve estar entre 0 e 5000 ms.')
    if type(value['hold_ms']) is not int or not 0<=value['hold_ms']<=2000 or type(value['mute']) is not bool:
        raise ValueError('Preferências de trilha inválidas.')
    tracks=value['playlist']
    if not isinstance(tracks,list) or len(tracks)>100:raise ValueError('A playlist aceita até 100 faixas.')
    clean=deepcopy(value);clean['playlist']=[];seen=set()
    for row in tracks:
        if not isinstance(row,dict) or set(row)!={'path','licensed'} or row['licensed'] is not True:
            raise ValueError('Cada faixa precisa de confirmação de licença para transmissão.')
        path=local_audio_path(row['path'],exists=False);key=os.path.normcase(path)
        if key not in seen:clean['playlist'].append({'path':path,'licensed':True});seen.add(key)
    return clean


class Preferences:
    def __init__(self,path=SETTINGS_PATH):
        self.path=Path(path) if path else None;self.error=''
    def load(self):
        if not self.path or not self.path.exists():return deepcopy(DEFAULT)
        try:
            raw=self.path.read_bytes()
            if len(raw)>256*1024:raise ValueError('Tamanho inválido')
            return validate_preferences(json.loads(raw))
        except (OSError,ValueError,TypeError):
            self.error='Preferências não carregadas; revise e salve os ajustes.'
            return deepcopy(DEFAULT)
    def save(self,value):
        clean=validate_preferences(value)
        if self.path:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix('.tmp.'+uuid.uuid4().hex)
            try:
                if self.error and self.path.exists():
                    self.path.with_suffix('.previous.json').write_bytes(self.path.read_bytes())
                with temporary.open('w',encoding='utf-8') as handle:
                    json.dump(clean,handle,ensure_ascii=False,indent=2);handle.flush();os.fsync(handle.fileno())
                os.replace(temporary,self.path)
            finally:temporary.unlink(missing_ok=True)
        self.error='';return clean


class MusicBackendError(RuntimeError):
    def __init__(self,code):
        self.code=int(code);super().__init__('MCI_AUDIO_'+str(self.code))


class WindowsMusicBackend:
    """Dedicated reserved Sound channel; never uses the TTS music stream.

    WAV is decoded once per track in local memory. Channel gain is applied by
    SDL's mixer, independently of pygame.mixer.music and Windows master volume.
    """
    CHANNEL=0
    def __init__(self):
        import pygame
        self.pygame=pygame
        self.owner=threading.get_ident();self.opened=False;self.paused=False
        if not pygame.mixer.get_init():pygame.mixer.init()
        if pygame.mixer.get_num_channels()<=self.CHANNEL:
            pygame.mixer.set_num_channels(self.CHANNEL+1)
        pygame.mixer.set_reserved(self.CHANNEL+1)
        self.channel=pygame.mixer.Channel(self.CHANNEL);self.sound=None
    def _check(self):
        if self.owner!=threading.get_ident():raise RuntimeError('MUSIC_THREAD_OWNER')
    def open(self,path):
        self._check();self.close()
        self.sound=self.pygame.mixer.Sound(local_audio_path(path))
        self.channel.set_volume(0);self.opened=True
    def play(self):
        self._check();self.channel.play(self.sound);self.paused=False
    def pause(self):
        self._check();self.channel.pause();self.paused=True
    def resume(self):
        self._check();self.channel.unpause();self.paused=False
    def mode(self):
        self._check()
        return 'paused' if self.paused else 'playing' if self.channel.get_busy() else 'stopped'
    def set_volume(self,percent):
        self._check();self.channel.set_volume(max(0.,min(1.,float(percent)/100)))
    def close(self):
        self._check()
        if self.opened:self.channel.stop()
        self.sound=None;self.opened=False;self.paused=False


class SoundtrackController:
    def __init__(self,path=SETTINGS_PATH,*,backend_factory=WindowsMusicBackend,clock=time.monotonic,
                 threaded=True,on_log=None,tts_snapshot=None,rng=None):
        self.store=Preferences(path);self.preferences=self.store.load()
        self.clock=clock;self.backend_factory=backend_factory;self.backend=None;self.threaded=threaded
        self.rng=rng or random.Random()
        self.lock=threading.RLock();self.condition=threading.Condition(self.lock)
        self.persist_lock=threading.Lock();self.wake=threading.Event();self.worker=None
        self.commands=deque();self.enabled=False;self.paused=False;self.closing=False;self.closed=False
        self.state='STOPPED';self.selected=0;self.current_path='';self.unavailable=set()
        self.volume=0.;self.target=None;self.fade_from=0.;self.fade_at=clock();self.fade_seconds=0.
        self.next_poll=0.;self.last_error=self.store.error;self.on_log=on_log;self.counts=Counter()
        self.tts_snapshot=tts_snapshot
        self.voice_id=None;self.voice_active=False;self.preparing=False;self.duck_latched=False
        self.release_at=None;self.tts_state='IDLE';self.tts_queue=0;self.tts_paused=False

    def _log(self,event,**details):
        if self.on_log:
            try:self.on_log(event+' | '+json.dumps(details,separators=(',',':')))
            except Exception:pass

    def _ensure_worker(self):
        if self.threaded and (not self.worker or not self.worker.is_alive()) and not self.closed:
            self.worker=threading.Thread(target=self._run,name='zuko-soundtrack',daemon=True);self.worker.start()

    def _enqueue(self,command,value=None):
        with self.condition:
            if self.closed or (self.closing and command!='close'):return False
            if command in {'stop','close'}:self.commands.clear()
            if len(self.commands)>=64:return False
            self.commands.append((command,value));self._ensure_worker();self.wake.set();self.condition.notify_all()
            return True

    def _commit(self,value):
        with self.persist_lock:
            clean=self.store.save(value)
            with self.condition:
                self.preferences=clean;self.last_error='';self.wake.set();self.condition.notify_all()

    def add_files(self,paths,*,licensed=False):
        if licensed is not True:raise ValueError('Confirme a licença de uso em transmissão antes de adicionar.')
        with self.lock:value=deepcopy(self.preferences)
        for source in paths:
            path=local_audio_path(source)
            if not any(os.path.normcase(row['path'])==os.path.normcase(path) for row in value['playlist']):
                value['playlist'].append({'path':path,'licensed':True})
        self._commit(value)
        with self.lock:active=self.enabled
        if active:self._enqueue('sync')
        return len(value['playlist'])

    def remove(self,index):
        with self.lock:value=deepcopy(self.preferences)
        if not 0<=index<len(value['playlist']):return False
        value['playlist'].pop(index);self._commit(value)
        with self.lock:self.selected=min(self.selected,max(0,len(value['playlist'])-1));active=self.enabled
        if active:self._enqueue('sync')
        return True

    def move(self,index,delta):
        with self.lock:value=deepcopy(self.preferences)
        target=index+delta
        if not 0<=index<len(value['playlist']) or not 0<=target<len(value['playlist']):return False
        value['playlist'][index],value['playlist'][target]=value['playlist'][target],value['playlist'][index]
        self._commit(value)
        with self.lock:self.selected=target;active=self.enabled
        if active:self._enqueue('sync')
        return True

    def clear(self):
        with self.lock:value=deepcopy(self.preferences)
        value['playlist']=[];self._commit(value);self.stop()

    def save_levels(self,normal,speech,duck_ms=300,restore_ms=800):
        with self.lock:value=deepcopy(self.preferences)
        value.update(normal_volume=int(normal),speech_volume=int(speech),duck_ms=int(duck_ms),restore_ms=int(restore_ms))
        self._commit(value)

    def set_mute(self,muted):
        with self.lock:value=deepcopy(self.preferences)
        value['mute']=bool(muted);self._commit(value)

    def set_shuffle(self,enabled):
        with self.lock:value=deepcopy(self.preferences)
        value['shuffle']=bool(enabled);self._commit(value)

    def start(self,index=None):
        with self.condition:
            if self.closed or self.closing or not self.preferences['playlist']:return False
            if index is not None:
                if not 0<=index<len(self.preferences['playlist']):return False
                self.selected=index
            elif self.enabled and self.state in {'STARTING','PLAYING'}:return True
            self.enabled=True;self.paused=False;self.state='STARTING';self.unavailable.clear()
        return self._enqueue('play',self.selected)

    def stop(self):
        with self.condition:
            self.enabled=False;self.paused=False;self.condition.notify_all()
            if not self.worker and not self.backend:self.commands.clear();self.state='STOPPED';return True
        return self._enqueue('stop')

    def pause(self):
        with self.lock:
            if not self.enabled:return False
            self.paused=True
        return self._enqueue('pause')

    def resume(self):
        with self.lock:
            if not self.enabled:return False
            self.paused=False
        return self._enqueue('resume')

    def next_track(self,direction=1):
        with self.lock:
            tracks=self.preferences['playlist']
            if not tracks:return False
            if self.preferences.get('shuffle') and direction>0 and len(tracks)>1:
                index=self.rng.choice([i for i in range(len(tracks)) if i!=self.selected])
            else:index=(self.selected+direction)%len(tracks)
            self.selected=index
            active=self.enabled
        return self._enqueue('play',index) if active else True

    def _quiet_release(self):
        busy=(self.voice_active or self.preparing or
              (not self.tts_paused and (self.tts_queue>0 or self.tts_state in {'SYNTHESIZING','PLAYING','CANCELLING'})))
        if busy:self.release_at=None
        elif self.duck_latched and self.release_at is None:
            self.release_at=self.clock()+self.preferences['hold_ms']/1000

    def tts_event(self,event,response=None,detail='',snapshot=None):
        snapshot=snapshot or {};ident=getattr(response,'comment_id',None)
        with self.condition:
            self.tts_state=str(snapshot.get('TTS_STATE',self.tts_state))
            self.tts_queue=int(snapshot.get('TTS_QUEUE_DEPTH',0));self.tts_paused=bool(snapshot.get('TTS_PAUSED',False))
            if event=='TTS_STATE':self.tts_state=detail
            if event=='TTS_INICIO' or (event=='TTS_STATE' and detail=='PLAYING') or (event=='TTS_SNAPSHOT' and self.tts_state=='PLAYING'):
                self.voice_active=True;self.preparing=False;self.duck_latched=True
                if ident:self.voice_id=ident
                self.release_at=None
            elif event in {'TTS_OK','TTS_CANCELLED','TTS_ERRO','TTS_SKIPPED','TTS_STALE_DROPPED'} and ident==self.voice_id:
                self.voice_active=False;self.preparing=False;self.voice_id=None;self.tts_state='IDLE'
            elif (event=='TTS_STATE' and detail in {'IDLE','ERROR'}) or (event=='TTS_SNAPSHOT' and self.tts_state in {'IDLE','ERROR'}):
                self.voice_active=False;self.preparing=False;self.voice_id=None
            self._quiet_release()
            if event!='TTS_SNAPSHOT':self.wake.set()
            self.condition.notify_all()

    def before_voice(self,response,cancelled=lambda:False):
        """Called after synthesis, before play; at most duck_ms + 150 ms wait."""
        started=time.monotonic()
        with self.condition:
            self.voice_id=getattr(response,'comment_id',None);self.preparing=True
            self.duck_latched=True;self.release_at=None;self.counts['preplay_gates']+=1
            self.wake.set()
            deadline=time.monotonic()+self.preferences['duck_ms']/1000+.15
            while (self.enabled and not self.paused and not self.closed and self.state not in {'ERROR','CLOSED'}
                   and not self.preferences['mute'] and self.volume>self.preferences['speech_volume']+.15):
                if cancelled():return False
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    self.counts['duck_timeouts']+=1;self.last_error='Ducking não confirmado; trilha interrompida por segurança.'
                    self.stop();self._log('SOUNDTRACK_DUCK_TIMEOUT');break
                self.condition.wait(min(.02,remaining))
            self.counts['preplay_wait_ms']+=round((time.monotonic()-started)*1000)
        return not cancelled()

    def _desired_volume(self,now):
        self._quiet_release()
        if self.release_at is not None and now>=self.release_at:
            self.duck_latched=False;self.release_at=None
        if self.preferences['mute']:return 0.
        return float(self.preferences['speech_volume'] if self.duck_latched else self.preferences['normal_volume'])

    def _play_index(self,index):
        with self.lock:tracks=deepcopy(self.preferences['playlist'])
        if not tracks:self.enabled=False;self._stop_backend();return
        for offset in range(len(tracks)):
            actual=(index+offset)%len(tracks);path=tracks[actual]['path']
            with self.lock:
                if not self.enabled or self.closing:return
                if path in self.unavailable:continue
            try:
                local_audio_path(path)
                if self.backend is None:self.backend=self.backend_factory()
                self.backend.open(path)  # Open at volume zero; never start a new track loud.
                with self.lock:active=self.enabled and not self.closing;paused=self.paused
                if not active:self.backend.close();return
                self.backend.play()
                if paused:self.backend.pause()
                with self.condition:
                    self.current_path=path;self.selected=actual;self.volume=0.;self.target=None
                    self.state='PAUSED' if paused else 'PLAYING';self.counts['tracks_started']+=1
                    self.last_error='';self.condition.notify_all()
                self._log('SOUNDTRACK_TRACK_STARTED',index=actual,format=Path(path).suffix.lower())
                return
            except Exception as error:
                with self.lock:self.unavailable.add(path);self.counts['track_errors']+=1
                self._log('SOUNDTRACK_TRACK_ERROR',index=actual,error=type(error).__name__,code=getattr(error,'code',None))
                if self.backend:
                    try:self.backend.close()
                    except Exception:pass
        with self.condition:
            self.enabled=False;self.state='ERROR';self.current_path='';self.volume=0
            self.last_error='Nenhuma faixa pôde ser reproduzida; confira os arquivos locais.';self.condition.notify_all()

    def _stop_backend(self):
        if self.backend:self.backend.close()
        with self.condition:
            self.current_path='';self.volume=0.;self.target=None
            self.state='STOPPED';self.condition.notify_all()

    def _command(self,action,value):
        if action=='close':self._stop_backend();self.closed=True;self.state='CLOSED';return False
        if action=='stop':self._stop_backend()
        elif action=='play':self._play_index(value)
        elif action=='pause' and self.backend and self.current_path and self.state=='PLAYING':
            self.backend.pause();self.state='PAUSED'
        elif action=='resume' and self.backend and self.current_path and self.state=='PAUSED':
            with self.lock:volume=min(self.volume,self._desired_volume(self.clock()))
            self.backend.set_volume(volume)
            with self.lock:self.volume=volume;self.target=None
            self.backend.resume();self.state='PLAYING'
        elif action=='sync':
            with self.lock:tracks=deepcopy(self.preferences['playlist']);path=self.current_path
            present=next((i for i,row in enumerate(tracks) if row['path']==path),None)
            if present is not None:self.selected=present
            elif tracks and self.enabled:self._play_index(min(self.selected,len(tracks)-1))
            else:self._stop_backend();self.enabled=False
        return True

    def step(self):
        """One deterministic control tick, also used with a virtual clock in tests."""
        try:
            if callable(self.tts_snapshot):
                self.tts_event('TTS_SNAPSHOT',snapshot=self.tts_snapshot())
            with self.lock:commands=list(self.commands);self.commands.clear()
            for action,value in commands:
                if not self._command(action,value):return False
            now=self.clock()
            with self.lock:
                desired=self._desired_volume(now)
                if self.target is None or abs(desired-self.target)>.001:
                    self.fade_from=self.volume;self.fade_at=now;self.target=desired
                    duration=0 if self.preferences['mute'] else self.preferences['duck_ms'] if desired<self.volume else self.preferences['restore_ms']
                    self.fade_seconds=duration/1000
                ratio=1 if not self.fade_seconds else min(1,max(0,(now-self.fade_at)/self.fade_seconds))
                volume=self.fade_from+(self.target-self.fade_from)*ratio
                active=bool(self.backend and self.current_path)
            if active:
                self.backend.set_volume(volume)
                with self.condition:self.volume=volume;self.condition.notify_all()
            with self.lock:poll=self.enabled and not self.paused and self.current_path and now>=self.next_poll
            if poll:
                self.next_poll=now+.05
                if self.backend.mode()=='stopped':
                    with self.lock:
                        length=len(self.preferences['playlist'])
                        if length and self.preferences.get('shuffle') and length>1:
                            index=self.rng.choice([i for i in range(length) if i!=self.selected])
                        else:index=(self.selected+1)%length if length else 0
                        if index==0:self.counts['playlist_loops']+=1
                    self._play_index(index)
            return not self.closed
        except Exception as error:
            try:self._stop_backend()
            except Exception:pass
            with self.condition:
                self.enabled=False;self.state='ERROR';self.volume=0.;self.counts['backend_errors']+=1
                self.last_error='Falha no áudio da trilha ('+type(error).__name__+'); voz preservada.'
                self.condition.notify_all()
            self._log('SOUNDTRACK_ERROR',error=type(error).__name__,code=getattr(error,'code',None))
            return not self.closing

    def _run(self):
        try:
            while self.step():
                with self.lock:delay=.02 if self.enabled or self.current_path or self.commands else .2
                self.wake.wait(delay);self.wake.clear()
        finally:
            if self.backend:
                try:self.backend.close()
                except Exception:pass
            with self.condition:
                self.closed=self.closing;self.enabled=False;self.volume=0.
                if self.closing:self.state='CLOSED'
                self.condition.notify_all()

    def snapshot(self):
        with self.lock:
            return {'enabled':self.enabled,'paused':self.paused,'state':self.state,'closed':self.closed,
                'preferences':deepcopy(self.preferences),'selected':self.selected,
                'current':Path(self.current_path).name if self.current_path else '',
                'volume':round(self.volume,2),'ducked':self.duck_latched,
                'voice_playing':self.voice_active,'error':self.last_error,'counts':dict(self.counts),
                'worker_alive':bool(self.worker and self.worker.is_alive())}

    def close(self):
        with self.condition:
            if self.closed:return True
            self.closing=True;self.enabled=False;self.condition.notify_all()
            if not self.worker and not self.backend:self.commands.clear();self.closed=True;self.state='CLOSED';return True
        self._enqueue('close')
        if not self.threaded:self.step()
        elif self.worker is not threading.current_thread():self.worker.join(timeout=3)
        return not self.worker or not self.worker.is_alive()
