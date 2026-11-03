"""One owned offline Windows speech process, reused by the serial TTS queue."""
from pathlib import Path
from collections import deque
import atexit,json,logging,os,queue,subprocess,threading,time

logger=logging.getLogger(__name__)

class WorkerFailure(RuntimeError):pass

class LocalVoiceWorker:
    def __init__(self, graceful_shutdown_timeout=2.0, forced_shutdown_timeout=2.0):
        self.lock=threading.Lock();self._close_lock=threading.RLock();self.process=None;self.messages=queue.Queue();self.voices=[]
        self.errors=deque(maxlen=8);self.ready=False;self.startup_ms=0.
        self.graceful_shutdown_timeout=max(.1,float(graceful_shutdown_timeout))
        self.forced_shutdown_timeout=max(.1,float(forced_shutdown_timeout))
        self._last_close_result={'status':'NOT_CLOSED','exited':None,'pid':None}
    def _reader(self,stream,messages):
        try:
            for line in iter(stream.readline,b''):
                try:messages.put(json.loads(line.decode('utf-8-sig')))
                except ValueError:continue
        finally:messages.put(None)
    def _stderr(self,stream):
        for line in iter(stream.readline,b''):self.errors.append(line.decode('utf-8-sig',errors='replace')[-300:])
    def _receive(self,timeout,cancelled):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if cancelled():self.close();raise InterruptedError('LOCAL_TTS_CANCELLED')
            try:message=self.messages.get(timeout=min(.1,max(.001,deadline-time.monotonic())))
            except queue.Empty:continue
            if message is None:
                self.close();raise WorkerFailure('LOCAL_TTS_PROCESS_EXITED: '+''.join(self.errors)[-300:])
            return message
        self.close();raise WorkerFailure('LOCAL_TTS_WORKER_TIMEOUT: processo local encerrado no prazo definido.')
    def _start(self,cancelled,timeout=30):
        if self.process and self.process.poll() is None and self.ready:return
        close_result=self.close()
        if not close_result.get('exited',True):
            raise WorkerFailure('LOCAL_TTS_PREVIOUS_WORKER_STILL_RUNNING')
        self.messages=queue.Queue();self.errors.clear()
        executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        script=Path(__file__).with_name('zuko_local_tts.ps1')
        started=time.monotonic()
        self.process=subprocess.Popen([str(executable),'-NoProfile','-NonInteractive','-File',str(script),'-Action','worker'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        threading.Thread(target=self._reader,args=(self.process.stdout,self.messages),daemon=True,name='local-voice-protocol').start()
        threading.Thread(target=self._stderr,args=(self.process.stderr,),daemon=True,name='local-voice-errors').start()
        message=self._receive(timeout,cancelled)
        if not message.get('ready'):self.close();raise WorkerFailure('LOCAL_TTS_WORKER_NOT_READY')
        self.voices=[v for v in message.get('voices',[]) if v.get('language')=='pt-BR']
        self.ready=True;self.startup_ms=round((time.monotonic()-started)*1000,2)
    def list_voices(self,cancelled=lambda:False,startup_timeout=30):
        with self.lock:self._start(cancelled,startup_timeout);return list(self.voices)
    def synthesize(self,text,path,name,rate,cancelled=lambda:False,timeout=12,startup_timeout=30):
        with self.lock:
            self._start(cancelled,startup_timeout)
            request={'op':'synthesize','text':str(text)[:6000],'output':str(path),'voice':name,'rate':int(rate)}
            try:
                self.process.stdin.write((json.dumps(request,ensure_ascii=False)+'\n').encode('utf-8'));self.process.stdin.flush()
            except (OSError,ValueError):self.close();raise WorkerFailure('LOCAL_TTS_INPUT_FAILED')
            result=self._receive(timeout,cancelled)
            if not result.get('ok'):raise WorkerFailure(str(result.get('error','LOCAL_TTS_SYNTHESIS_FAILED'))[:400])
            return result
    def snapshot(self):
        return {'ready':self.ready,'pid':self.process.pid if self.process and self.process.poll() is None else None,
                'startup_ms':self.startup_ms,'voices':[v['name'] for v in self.voices],
                'last_close':dict(self._last_close_result)}
    def close(self):
        """Close only the PowerShell process tree owned by this worker.

        Normal protocol shutdown gets a bounded grace period. If it misses the
        deadline, taskkill targets the exact Popen PID and its descendants;
        the owned Popen is then waited and killed as a final fallback.
        """
        with self._close_lock:
            process=self.process
            self.ready=False
            if process is None:
                result=dict(self._last_close_result)
                if result.get('status')=='NOT_CLOSED':
                    result={'status':'ALREADY_CLOSED','exited':True,'pid':None}
                self._last_close_result=result
                return dict(result)

            pid=getattr(process,'pid',None)
            result={'status':'CLOSE_REQUESTED','exited':False,'pid':pid,
                    'graceful':False,'tree_kill_attempted':False,'forced':False}
            try:
                if process.poll() is not None:
                    result.update(status='ALREADY_EXITED',exited=True)
                else:
                    try:
                        stdin=getattr(process,'stdin',None)
                        if stdin is not None:
                            stdin.write(b'{"op":"close"}\n');stdin.flush()
                        process.wait(timeout=self.graceful_shutdown_timeout)
                        result.update(status='GRACEFUL',exited=True,graceful=True)
                    except subprocess.TimeoutExpired:
                        result['status']='GRACEFUL_TIMEOUT'
                    except (OSError,ValueError) as exc:
                        result['status']='GRACEFUL_REQUEST_FAILED'
                        result['request_error']=type(exc).__name__

                    if not result['exited'] and process.poll() is None:
                        result['tree_kill_attempted']=True
                        if os.name=='nt' and pid is not None:
                            try:
                                killed=subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],
                                    capture_output=True,text=True,shell=False,
                                    timeout=self.forced_shutdown_timeout,check=False)
                                result['taskkill_returncode']=killed.returncode
                            except (OSError,subprocess.TimeoutExpired) as exc:
                                result['taskkill_error']=type(exc).__name__
                        if process.poll() is None:
                            try:
                                process.wait(timeout=self.forced_shutdown_timeout)
                            except subprocess.TimeoutExpired:
                                try:
                                    process.kill()
                                    result['forced']=True
                                except (OSError,ProcessLookupError) as exc:
                                    result['kill_error']=type(exc).__name__
                                try:
                                    process.wait(timeout=self.forced_shutdown_timeout)
                                except subprocess.TimeoutExpired:
                                    result['status']='FORCED_EXIT_TIMEOUT'
                            except (OSError,ValueError) as exc:
                                result['wait_error']=type(exc).__name__
                        if process.poll() is not None:
                            result.update(status='FORCED' if result['forced'] or result['tree_kill_attempted'] else 'EXITED',
                                          exited=True)
            except Exception as exc:
                # Cleanup is best-effort and must never escape into the serial
                # TTS manager thread.
                result.update(status='CLOSE_ERROR',close_error=type(exc).__name__)
                logger.exception('ZUKO local TTS worker close failed (pid=%s)',pid)
            finally:
                for stream in (getattr(process,'stdin',None),getattr(process,'stdout',None),getattr(process,'stderr',None)):
                    if stream is not None:
                        try:stream.close()
                        except Exception as exc:
                            result.setdefault('stream_close_errors',[]).append(type(exc).__name__)
                try:
                    exited=process.poll() is not None
                except Exception as exc:
                    exited=False
                    result.setdefault('poll_error',type(exc).__name__)
                if exited:
                    result['exited']=True
                    if self.process is process:self.process=None
                    self.voices=[]
                else:
                    # Retain the handle so an explicit repeated close can
                    # retry and so the process is never silently orphaned.
                    self.process=process
                self._last_close_result=dict(result)
                logger.info('ZUKO local TTS worker close: %s',result)
            return dict(result)

worker=LocalVoiceWorker()
atexit.register(worker.close)
