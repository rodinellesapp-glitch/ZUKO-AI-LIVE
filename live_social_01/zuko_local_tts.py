"""Bounded offline Windows speech. No registry edits, downloads or network."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import threading
import time
import wave
from zuko_voice_worker import worker,WorkerFailure

ROOT=Path(__file__).resolve().parents[1]
TEMP=ROOT/'runtime'/'voice'
SCRIPT=Path(__file__).with_suffix('.ps1')
POWERSHELL=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'


class LocalVoiceUnavailable(RuntimeError):pass


class VoiceHealth:
    def __init__(self):
        self.lock=threading.RLock();self.state='UNVERIFIED';self.voice='';self.backend='';self.error=''
        self.started=0;self.completed=0;self.checked_at=0.
    def update(self,state,*,voice=None,backend=None,error=''):
        with self.lock:
            self.state=state;self.error=str(error)[:500]
            if voice is not None:self.voice=voice
            if backend is not None:self.backend=backend
            if state=='READY':self.checked_at=time.time();self.completed+=1
            if state=='PLAYING':self.started+=1
    def snapshot(self):
        with self.lock:return {'state':self.state,'voice':self.voice,'backend':self.backend,'error':self.error,
            'playback_started':self.started,'playback_completed':self.completed,'checked_at':self.checked_at,
            'ready':self.state in {'READY','SYNTHESIZING','PLAYING'} and self.completed>0}


health=VoiceHealth()
_owner=threading.Lock()
_candidate_lock=threading.Lock()
_candidates=[]
_preferred=None


def run_helper(arguments,*,cancelled=lambda:False,timeout=12):
    """Own exactly one child; cancel/timeout kills and reaps that child only."""
    process=subprocess.Popen([str(POWERSHELL),'-NoProfile','-NonInteractive','-File',str(SCRIPT),*arguments],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    deadline=time.monotonic()+timeout
    try:
        while True:
            if cancelled():raise InterruptedError('LOCAL_TTS_CANCELLED')
            remaining=deadline-time.monotonic()
            if remaining<=0:raise LocalVoiceUnavailable('LOCAL_TTS_TIMEOUT: síntese local interrompida no prazo definido.')
            try:
                stdout,stderr=process.communicate(timeout=min(.1,remaining));break
            except subprocess.TimeoutExpired:continue
        if process.returncode:
            detail=stderr.decode('utf-8-sig',errors='replace').strip()[-400:]
            raise LocalVoiceUnavailable(detail or 'LOCAL_TTS_PROCESS_FAILED')
        return stdout.decode('utf-8-sig',errors='replace').strip()
    finally:
        if process.poll() is None:process.kill()
        process.communicate()


def installed_voices(*,cancelled=lambda:False,refresh=False,deadline=None):
    global _candidates
    with _candidate_lock:
        if _candidates and not refresh:return list(_candidates)
        errors=[]
        # WinRT uses the installed OneCore voices directly. SAPI remains a local
        # compatibility fallback when WinRT cannot enumerate pt-BR voices.
        for backend in ('winrt','sapi'):
            try:
                timeout=min(8,deadline-time.monotonic()) if deadline is not None else 8
                if timeout<=0:break
                if backend=='winrt':
                    startup=min(30,deadline-time.monotonic()) if deadline is not None else 30
                    rows=worker.list_voices(cancelled,startup_timeout=startup)
                else:rows=json.loads(run_helper(['-Action','list','-Backend',backend],cancelled=cancelled,timeout=timeout))
                if isinstance(rows,dict):rows=[rows]
                rows=[r for r in rows if r.get('language')=='pt-BR' and isinstance(r.get('name'),str)]
                if rows:
                    _candidates=rows;return list(rows)
            except (LocalVoiceUnavailable,WorkerFailure,ValueError,OSError) as error:errors.append(str(error))
        raise LocalVoiceUnavailable('Nenhuma voz local pt-BR utilizável. '+('; '.join(errors))[:400])


def synthesize(text,output_path,rate=2,*,cancelled=lambda:False,preferred='Microsoft Maria'):
    global _preferred
    if not str(text).strip():raise LocalVoiceUnavailable('Texto vazio; nenhuma síntese iniciada.')
    # The helper verifies pt-BR and the exact installed name during synthesis.
    # Avoid a separate cold PowerShell enumeration on the normal Maria route.
    rows=[{'name':preferred,'backend':'winrt','language':'pt-BR'}]
    discovered=False;tried=set();deadline=time.monotonic()+45
    TEMP.mkdir(parents=True,exist_ok=True)
    errors=[]
    with tempfile.TemporaryDirectory(prefix='synthesis-',dir=TEMP) as directory:
        source=Path(directory)/'speech.txt';source.write_text(str(text)[:6000],encoding='utf-8')
        while rows:
            row=rows.pop(0);key=(row['backend'],row['name'])
            if key in tried:continue
            tried.add(key)
            if cancelled():raise InterruptedError('LOCAL_TTS_CANCELLED')
            try:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise LocalVoiceUnavailable('LOCAL_TTS_TOTAL_TIMEOUT')
                if row['backend']=='winrt':
                    worker.synthesize(text,str(output_path),row['name'],max(-10,min(10,int(rate))),cancelled,
                        timeout=min(12,remaining),startup_timeout=min(30,remaining))
                else:
                    run_helper(['-Action','synthesize','-Backend',row['backend'],'-VoiceName',row['name'],
                        '-TextPath',str(source),'-OutputPath',str(output_path),'-Rate',str(max(-10,min(10,int(rate))))],
                        cancelled=cancelled,timeout=min(12,remaining))
                with wave.open(str(output_path),'rb') as audio:
                    if audio.getnframes()<100 or audio.getsampwidth()!=2:raise ValueError('LOCAL_WAV_INVALID')
                    if not any(audio.readframes(min(audio.getnframes(),audio.getframerate()*5))):
                        raise ValueError('LOCAL_WAV_SILENT')
                _preferred=dict(row)
                return dict(row)
            except (LocalVoiceUnavailable,WorkerFailure,OSError,ValueError,wave.Error) as error:
                errors.append(row['name']+': '+str(error))
                if not discovered:
                    discovered=True
                    try:
                        alternatives=installed_voices(cancelled=cancelled,refresh=True,deadline=deadline)
                        alternatives.sort(key=lambda item:(0 if preferred.casefold() in item['name'].casefold() else 1,
                                                           0 if item==_preferred else 1,item['name']))
                        rows.extend(alternatives)
                    except (LocalVoiceUnavailable,OSError) as failure:errors.append(str(failure))
        raise LocalVoiceUnavailable('Voz local indisponível; geração de respostas bloqueada. '+('; '.join(errors))[:400])


def speak(text,cancelar=lambda:False,*,windows_rate=2,on_synthesized=None,on_playback_started=None,**_):
    """One owner and the existing TTS music stream; soundtrack stays separate."""
    import pygame
    with _owner:
        TEMP.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='speech-',suffix='.wav',dir=TEMP);os.close(fd)
        loaded=False;started=False
        try:
            health.update('SYNTHESIZING')
            row=synthesize(text,name,windows_rate,cancelled=cancelar)
            health.update('SYNTHESIZING',voice=row['name'],backend=row['backend'])
            if cancelar():raise InterruptedError('LOCAL_TTS_CANCELLED')
            if on_synthesized:on_synthesized()
            if cancelar():raise InterruptedError('LOCAL_TTS_CANCELLED')
            if not pygame.mixer.get_init():pygame.mixer.init()
            pygame.mixer.music.load(name);loaded=True
            pygame.mixer.music.play()
            if not pygame.mixer.music.get_busy():raise LocalVoiceUnavailable('LOCAL_AUDIO_DID_NOT_START')
            started=True;health.update('PLAYING')
            if on_playback_started:on_playback_started()
            while pygame.mixer.music.get_busy():
                if cancelar():raise InterruptedError('LOCAL_TTS_CANCELLED')
                time.sleep(.02)
            health.update('READY')
            return row
        except InterruptedError:
            health.update('UNVERIFIED' if not health.snapshot()['completed'] else 'READY')
            raise
        except Exception as error:
            health.update('UNAVAILABLE',error=error)
            raise
        finally:
            if loaded:pygame.mixer.music.stop();pygame.mixer.music.unload()
            Path(name).unlink(missing_ok=True)
