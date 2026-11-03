"""Local transport observer. Admission and arbitration stay in Live Social."""
import json
import queue
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / 'assistente_avatar/visual-tests/zig-viewer-event-bridge-354'
MAPPING = {'VIEWER_JOIN':'JOIN','CHAT_MESSAGE':'COMMENT','CHAT':'COMMENT','FOLLOW':'FOLLOW',
           'SUBSCRIBE':'FOLLOW','LIKE_EVENT':'LIKE','LIKE':'LIKE','SHARE_EVENT':'SHARE',
           'GIFT_EVENT':'GIFT_SMALL','GIFT':'GIFT_SMALL','SUPER_CHAT':'GIFT_BIG'}


class ViewerEventBridge:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.clients, self.lock = [], threading.Lock()
        self.trace, self.acks, self.errors = [], [], []
        self.pending = queue.Queue(maxsize=256)
        self.worker = self.cache = None
        self.clips = {}
        self.dropped_offline = 0
        self.http = None
        self.input_types = {}

    def start(self):
        if not Path(r'C:\Program Files\nodejs\node.exe').is_file():raise FileNotFoundError('Local Node runtime unavailable')
        if not (OUTPUT/'attach354.mjs').is_file():raise FileNotFoundError('Approved local bridge loader unavailable')
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def setup(self):
                super().setup()
                import socket
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            def allowed(self):
                return self.headers.get('Origin') in (None, 'http://127.0.0.1:4206') and self.headers.get('Host') == '127.0.0.1:4210'
            def send_headers(self, kind, size=None):
                self.send_response(200); self.send_header('Content-Type',kind)
                self.send_header('Access-Control-Allow-Origin','http://127.0.0.1:4206')
                self.send_header('Cache-Control','no-store')
                if size is not None:self.send_header('Content-Length',str(size))
                self.end_headers()
            def do_GET(self):
                if not self.allowed(): self.send_error(403); return
                if self.path == '/health':
                    b=json.dumps({'bridge':'354','token':owner.token,'server_at':time.perf_counter()*1000}).encode()
                    self.send_headers('application/json',len(b));self.wfile.write(b);return
                if self.path == '/events?token='+owner.token:
                    q=queue.Queue(maxsize=256)
                    with owner.lock:owner.clients.append(q)
                    self.send_headers('text/event-stream')
                    try:
                        self.wfile.write(b': connected\n\n');self.wfile.flush()
                        while True:
                            try:item=q.get(timeout=1);b=('data: '+json.dumps(item,ensure_ascii=False)+'\n\n').encode()
                            except queue.Empty:b=b': heartbeat\n\n'
                            self.wfile.write(b);self.wfile.flush()
                    except (BrokenPipeError,ConnectionResetError,OSError):pass
                    finally:
                        with owner.lock:
                            if q in owner.clients:owner.clients.remove(q)
                    return
                if self.path.startswith('/audio/'):
                    b=owner.clips.get(self.path)
                    if b is not None:self.send_headers('audio/wav',len(b));self.wfile.write(b);return
                self.send_error(404)
            def do_POST(self):
                if not self.allowed() or self.path!='/ack?token='+owner.token:self.send_error(403);return
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384:self.send_error(400);return
                try:r=json.loads(self.rfile.read(size));r['ack_server_at']=time.perf_counter()*1000;owner.acks.append(r)
                except (ValueError,TypeError):self.send_error(400);return
                self.send_headers('application/json',2);self.wfile.write(b'{}')
            def log_message(self,*a):pass
        self.http=ThreadingHTTPServer(('127.0.0.1',4210),Handler);self.http.daemon_threads=True
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        threading.Thread(target=self._prepare,daemon=True).start()
        self.injector=subprocess.Popen([r'C:\Program Files\nodejs\node.exe',str(OUTPUT/'attach354.mjs')],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        return self

    def close(self):
        if getattr(self,'injector',None) and self.injector.poll() is None:self.injector.terminate()
        if self.worker and self.worker.poll() is None:self.worker.terminate()
        if self.http:threading.Thread(target=self.http.shutdown,daemon=True).start()
        try:self.pending.put_nowait(None)
        except queue.Full:pass

    def publish(self, decision):
        """Already-dispatched contract only; no new priorities or dedup policy."""
        d=dict(decision);d['decision_to_bridge_at']=time.perf_counter()*1000
        d.setdefault('decision_at_ms',d['decision_to_bridge_at'])
        with self.lock:
            if not self.clients:self.dropped_offline+=1;return False
        try:self.pending.put_nowait(d);return True
        except queue.Full:self.errors.append('transport_capacity_exceeded');return False

    def _synth(self,text):
        import wave
        if self.cache is None:self.cache={}
        if text in self.cache:return self.cache[text]
        if self.worker is None:
            script=OUTPUT.parent/'zig-performance-fix-351/sapi351.ps1'
            self.worker=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-Warm'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1,creationflags=subprocess.CREATE_NO_WINDOW)
            ready=json.loads(self.worker.stdout.readline())
            if 'Maria' not in ready['voice']:raise RuntimeError('Approved Maria voice unavailable')
        folder=OUTPUT/'audio';folder.mkdir(exist_ok=True);p=folder/f'clip-{len(self.cache)+1}.wav'
        self.worker.stdin.write(json.dumps({'text':text,'output':str(p)},ensure_ascii=False)+'\n');self.worker.stdin.flush()
        timing=json.loads(self.worker.stdout.readline())
        with wave.open(str(p),'rb') as w:duration=w.getnframes()/w.getframerate()
        key='/audio/'+p.name;self.clips[key]=p.read_bytes()
        speech={'text':text,'duration':duration+1,'audio_url':'fixture','bridge_url':'http://127.0.0.1:4210'+key}
        self.cache[text]=speech;return speech

    def _prepare(self):
        while True:
            d=self.pending.get()
            if d is None:return
            try:
                if d.get('test_tts_text'):d['speech']=self._synth(d.pop('test_tts_text'))
                d['published_at']=time.perf_counter()*1000
                with self.lock:
                    for q in self.clients:
                        try:q.put_nowait(d)
                        except queue.Full:self.errors.append('subscriber_capacity_exceeded')
                self.trace.append(d)
                if len(self.trace)>5000:del self.trace[:500]
            except Exception as e:self.errors.append(str(e))

    def observe(self,unit):
        fd=unit.metadata.get('flow_decision');evidence=getattr(fd,'evidence',())
        input_ids=getattr(fd,'event_ids',())
        event=self.input_types.get(input_ids[0]) if input_ids else None
        kind=MAPPING.get(event.event_type if event else evidence[0].get('type') if evidence else unit.event_type)
        if kind=='GIFT_SMALL' and event and event.priority=='HIGH':kind='GIFT_BIG'
        if not kind and unit.requires_tts:kind='TALK'
        if not kind:return
        if unit.event_type=='SUPER_CHAT':kind='GIFT_BIG'
        self.publish({'event_id':unit.unit_id,'event_type':unit.event_type,'visual_event':kind,
            'decision':'DISPATCHED','priority':unit.priority,'intensity':50,'interrupt_allowed':False,
            'speech':{'text':getattr(unit.content_ref,'text',''),'duration':30,'audio_url':'fixture',
                      'native_audio':True,'native_id':unit.unit_id} if unit.requires_tts else None})


def install_event_bridge(monitor):
    """Add transport listeners, preserving original callbacks and audio ownership."""
    try:
        from zig_settings import create_bridge
        bridge=create_bridge(monitor);monitor.zig_event_bridge=bridge
        monitor.root.zig_settings_bridge=bridge
        accept=monitor.accept_platform_event
        def remember(event):
            bridge.input_types[event.event_id]=event
            if len(bridge.input_types)>4096:bridge.input_types.pop(next(iter(bridge.input_types)))
            return accept(event)
        monitor.accept_platform_event=remember
        dispatch=monitor.director.dispatch
        def observe(unit):
            try:bridge.observe(unit)
            except Exception as e:bridge.errors.append(str(e))
            return dispatch(unit)
        monitor.director.dispatch=observe
        audio_started=monitor.voice.on_audio_started;spoken=monitor.voice.on_spoken;tts_event=monitor.voice.on_tts_event
        def start(response,*args):
            result=audio_started(response,*args)
            bridge.publish({'control':'AUDIO_START','event_id':response.comment_id})
            return result
        def end(response,*args):
            bridge.publish({'control':'AUDIO_END','event_id':response.comment_id})
            return spoken(response,*args)
        def event(name,response=None,*args):
            if name in {'TTS_CANCELLED','TTS_ERRO','TTS_SKIPPED','TTS_STALE_DROPPED'} and response:bridge.publish({'control':'AUDIO_END','event_id':response.comment_id})
            return tts_event(name,response,*args)
        monitor.voice.on_audio_started=start;monitor.voice.on_spoken=end;monitor.voice.on_tts_event=event
        if getattr(monitor,'root',None):
            monitor.root.bind('<Destroy>',lambda e:bridge.close() if e.widget is monitor.root else None,add='+')
    except Exception as e:
        monitor._log('ZIG_BRIDGE_UNAVAILABLE | '+str(e))
