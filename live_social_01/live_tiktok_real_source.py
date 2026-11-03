from zuko_public_name import public_name
"""Unofficial TikTokLive 7.0.1 transport. RAM queue only; no JARVIS decisions.

COMMENT/JOIN manually confirmed by the operator in LAB 5.2. Other event
classes are library-supported, not evidence of successful live validation.
"""
import asyncio
from collections import Counter, deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import version
import json
import os
import logging
from pathlib import Path
import re
import threading
import time
import traceback
from urllib.parse import urlsplit
from live_tiktok_config import tiktok_config, tiktok_room_id
from live_tiktok_source import TikTokEventSource, CAPABILITIES

EVENTS={'COMMENT':('CommentEvent','CHAT_MESSAGE','chat'),
        'JOIN':('JoinEvent','VIEWER_JOIN','joins'),
        'LIKE':('LikeEvent','LIKE_EVENT','likes'),
        'FOLLOW':('FollowEvent','FOLLOW','follows'),
        'SHARE':('ShareEvent','SHARE_EVENT','shares'),
        'GIFT':('GiftEvent','GIFT_EVENT','gifts')}
_lease=threading.Lock()
_URL_RE=re.compile(r"https?://[^\s'\")\]]+",re.I)
_SECRET_RE=re.compile(r"(?i)\b(cookie|set-cookie|authorization)\b\s*([=:]\s*)(?:bearer|basic)\s+[^\s&,;]+|\b(cookie|set-cookie|authorization|sessionid|session_id|token|signature|sign_api_key|api_key)\b\s*([=:]\s*)[^\s&,;]+")
_JSON_ENDPOINTS={'/api-live/user/room','/room/check_alive'}


class TikTokHTTPResponseError(RuntimeError):
    """Safe transport error that retains response headers, never its body."""
    def __init__(self,response):
        super().__init__('TikTok JSON endpoint returned an unusable HTTP response')
        self.response=response


async def guard_json_response(response):
    """Reject blocked/non-JSON SDK API responses before SDK calls response.json()."""
    path=(response.url.path or '/').rstrip('/')
    if path not in _JSON_ENDPOINTS:return
    status=response.status_code
    if 300<=status<400:return  # Let HTTPX follow normal redirects and inspect the final response.
    content_type=response.headers.get('content-type','').split(';',1)[0].strip().casefold()
    is_json=content_type=='application/json' or content_type.endswith('+json')
    if status!=200 or not is_json:
        raise TikTokHTTPResponseError(response)


def parse_retry_after(value, now=None):
    """Return Retry-After seconds for RFC delta-seconds or HTTP-date values."""
    if not isinstance(value,str) or not value.strip():return None
    value=value.strip()
    if len(value)>128:return None
    if re.fullmatch(r'[0-9]+',value):return float(value)
    try:
        date=parsedate_to_datetime(value)
        if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
        current=datetime.fromtimestamp(time.time() if now is None else now,timezone.utc)
        return max(0.,(date-current).total_seconds())
    except (TypeError,ValueError,OverflowError):return None


class _TransportLogFilter(logging.Filter):
    def __init__(self,thread_id):super().__init__();self.thread_id=thread_id
    def filter(self,record):return record.thread!=self.thread_id


def load_sdk():
    # Import only on explicit start of the real source.
    from TikTokLive import TikTokLiveClient, events
    if version('TikTokLive')!='7.0.1':raise RuntimeError('TIKTOKLIVE_VERSION_MISMATCH')
    return TikTokLiveClient,events


def response_metadata(error):
    """Read only response metadata retained in exception frames; never read body/cookies."""
    rows=[];seen=set();pending=[error];visited=set()
    while pending:
        current=pending.pop()
        if id(current) in visited:continue
        visited.add(id(current))
        for linked in (current.__cause__,current.__context__):
            if linked is not None:pending.append(linked)
        direct=getattr(current,'response',None)
        candidates=[direct] if direct is not None else []
        tb=current.__traceback__
        while tb:
            candidates.extend(tb.tb_frame.f_locals.values())
            tb=tb.tb_next
        for value in candidates:
            try:
                status=getattr(value,'status_code',None);headers=getattr(value,'headers',None);url=getattr(value,'url',None)
                if type(status) is not int or headers is None or url is None:continue
                host=getattr(url,'host',None);path=getattr(url,'path',None)
                if not isinstance(host,str):
                    parsed=urlsplit(str(url));host=parsed.hostname or 'unknown';path=parsed.path
                retry_after=headers.get('retry-after')
                if parse_retry_after(retry_after) is None:retry_after=None
                item={'status':status,'content_type':headers.get('content-type'),
                    'content_length':headers.get('content-length'),'server':headers.get('server'),
                    'via':headers.get('via'),'retry_after':retry_after, 'host':host[:255],
                    'path':(path or '/')[:512]}
                key=tuple(item.values())
                if key not in seen:seen.add(key);rows.append(item)
            except Exception:continue
    return rows[:8]


def _sanitize_traceback(error):
    rendered=''.join(traceback.TracebackException.from_exception(error,capture_locals=False).format(chain=True))
    def clean_url(match):
        try:
            parsed=urlsplit(match.group(0));host=parsed.netloc.rsplit('@',1)[-1]
            return parsed.scheme+'://'+host+parsed.path
        except Exception:return '[URL_REMOVIDA]'
    rendered=_URL_RE.sub(clean_url,rendered)
    rendered=_SECRET_RE.sub(lambda match:(match.group(1)+match.group(2) if match.group(1) else match.group(3)+match.group(4))+'[REDACTED]',rendered)
    return rendered[:16000]


def error_diagnostic(error):
    responses=response_metadata(error)
    return {'exception':type(error).__name__,'category':error_category(error,responses),
        'responses':responses,'traceback':_sanitize_traceback(error)}


def error_category(error,responses=None):
    if responses is None:responses=response_metadata(error)
    if getattr(error,'winerror',None)==10013 or getattr(error,'errno',None)==13:return 'NETWORK_ACCESS_DENIED'
    names=set();reasons=set();visited=set();current=error
    while current is not None and id(current) not in visited:
        visited.add(id(current));names.update(c.__name__ for c in type(current).__mro__)
        reason=getattr(getattr(current,'reason',None),'name','')
        if reason:reasons.add(reason)
        current=current.__cause__ or current.__context__
    status=getattr(getattr(error,'response',None),'status_code',None)
    statuses=[row.get('status') for row in (responses or [])]
    if status is None and statuses:
        status=next((s for s in statuses if s in (401,403,429) or (type(s) is int and s>=500)),statuses[0])
    if status==401:return 'AUTH_REQUIRED'
    if status==403:return 'ACCESS_RESTRICTED'
    if status==429:return 'RATE_LIMITED'
    if type(status) is int and 400<=status<500:return 'HTTP_RESPONSE_ERROR'
    if type(status) is int and status>=500:return 'SERVICE_ERROR'
    if status==200 and 'TikTokHTTPResponseError' in names:return 'INVALID_RESPONSE'
    if names & {'ModuleNotFoundError','ImportError'}:return 'TIKTOKLIVE_DEPENDENCY_MISSING'
    if 'UserOfflineError' in names:return 'LIVE_OFFLINE'
    if 'FailedParseRoomIdError' in names:return 'ROOM_DISCOVERY_FAILED'
    if names & {'AgeRestrictedError','AuthenticatedWebSocketConnectionError','PremiumEndpointError'} or reasons & {'AUTHENTICATED_WS','PREMIUM_ENDPOINT'}:return 'AUTH_REQUIRED'
    if 'SignatureRateLimitError' in names or 'RATE_LIMIT' in reasons:return 'RATE_LIMITED'
    if 'JSONDecodeError' in names:return 'INVALID_RESPONSE'
    if 'UserNotFoundError' in names:return 'USER_NOT_FOUND'
    if names & {'OSError','TimeoutError','TimeoutException','ConnectTimeout','ReadTimeout','WriteTimeout','PoolTimeout',
        'ConnectionError','NetworkError','ConnectError','ProxyError','ConnectionClosedError','WebSocketException'}:return 'CONNECTION_FAILED'
    return 'LIBRARY_ERROR'


def public_string(value, limit):
    return value[:limit] if isinstance(value,str) and value else None


class TikTokRealEventSource(TikTokEventSource):
    name='TIKTOKLIVE'
    verified=True
    simulation=False

    def __init__(self,unique_id=None,ignore_broadcaster=True,*,sdk_loader=None,clock=time.monotonic,wall_clock=time.time,session_runner=None,diagnostic_directory=None):
        self.unique_id,_=tiktok_config(unique_id)
        self.room_id=tiktok_room_id(self.unique_id)
        if self.room_id is not None and (type(self.room_id) is not int or not 1<=self.room_id<=9999999999999999999):
            raise ValueError('TIKTOK_ROOM_ID_INVALID')
        self.ignore_broadcaster=ignore_broadcaster
        self._load=sdk_loader or load_sdk;self.clock=clock;self.wall_clock=wall_clock
        self._lock=threading.RLock();self._queue=deque();self._logs=deque(maxlen=80)
        self.counts=Counter();self._caps=dict.fromkeys(CAPABILITIES,False)
        self._state='STOPPED';self._reason='';self._thread=None;self._loop=None;self._task=None
        self._client=None;self._stopping=threading.Event();self._generation=0
        self.session_started_at=None;self.retry_after=0.;self._last_log={}
        self._reconnects=0;self.max_reconnects=3
        self.diagnostic_directory=Path(diagnostic_directory) if diagnostic_directory else Path(__file__).resolve().parent/'logs'
        self._last_diagnostic_path=None
        self._session_runner=session_runner or (lambda generation:asyncio.run(self._session(generation)))

    def _log(self,marker):
        # Content-free and bounded. Event flood does not flood persistent logs.
        with self._lock:
            now=self.clock()
            lifecycle=marker.startswith(('TIKTOK_REAL_SOURCE_','TIKTOK_REAL_CONNECT','TIKTOK_REAL_DISCONNECT','TIKTOK_REAL_LIVE_OFFLINE','TIKTOK_REAL_ERROR'))
            if lifecycle or now-self._last_log.get(marker,float('-inf'))>=1:
                self._last_log[marker]=now;self._logs.append(marker)

    def drain_logs(self):
        with self._lock:
            rows=list(self._logs);self._logs.clear();return rows

    def _state_set(self,state,reason=''):
        with self._lock:
            if self._stopping.is_set():return
            self._state,self._reason=state,reason
        self._log('TIKTOK_REAL_'+state)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():return not self._stopping.is_set()
            if self.clock()<self.retry_after:
                self._state='RATE_LIMITED';self._reason='RETRY_AFTER';return False
            if not _lease.acquire(blocking=False):
                self._state='ERROR';self._reason='TIKTOK_READER_ALREADY_ACTIVE';return False
            self._queue.clear();self._stopping.clear();self._generation+=1
            self._reconnects=0
            self._state='WAITING_FOR_LIVE';self._reason='';self.session_started_at=None
            self._thread=threading.Thread(target=self._run,args=(self._generation,),name='TikTokRealEventSource',daemon=True)
            self._log('TIKTOK_REAL_SOURCE_START');self._thread.start();return True

    def stop(self):
        # Tk never waits for network or joins the worker thread.
        with self._lock:
            self._stopping.set();self._state='STOPPED';self._queue.clear()
            loop,task=self._loop,self._task
        if loop and task and not loop.is_closed():
            try:loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:pass
        self._log('TIKTOK_REAL_SOURCE_STOP')

    def is_connected(self):
        with self._lock:return self._state=='CONNECTED' and not self._stopping.is_set()

    def capabilities(self):
        with self._lock:return dict(self._caps)

    def health(self):
        with self._lock:
            return {'connection':self._state,'reason':self._reason,'source':self.name,'verified':True,
                'broadcaster':'@'+self.unique_id,'worker_alive':bool(self._thread and self._thread.is_alive()),
                'capability_validation':{key:('VERIFIED_REAL' if self.counts.get('TIKTOK_REAL_'+{'chat':'CHAT','joins':'JOIN','likes':'LIKE','follows':'FOLLOW','shares':'SHARE','gifts':'GIFT'}.get(key,key.upper())+'_RECEIVED',0)>0 else 'SUPPORTED_UNVERIFIED')
                    if available else 'UNAVAILABLE' for key,available in self._caps.items()},
                'counts':dict(self.counts),'retry_after_seconds':max(0.,self.retry_after-self.clock()),
                'room_id_supplied':self.room_id is not None,
                'reconnect_attempts':self._reconnects,'max_reconnects':self.max_reconnects,
                'diagnostic_file':str(self._last_diagnostic_path) if self._last_diagnostic_path else None}

    def read_event(self):
        with self._lock:
            return self._queue.popleft() if self.is_connected() and self._queue else None

    def _receive(self,kind,event,generation):
        # Called in SDK loop; ONLY enqueue structural input. No Flow/AI/TTS here.
        with self._lock:
            if generation!=self._generation or not self.is_connected():return
            self.counts['TIKTOK_REAL_EVENTS_RECEIVED']+=1
            self.counts['TIKTOK_REAL_'+('CHAT' if kind=='COMMENT' else kind)+'_RECEIVED']+=1
            user=getattr(event,'user',None)
            handle=getattr(user,'unique_id',None)
            if (kind=='COMMENT' and self.ignore_broadcaster and isinstance(handle,str)
                    and handle.removeprefix('@').casefold()==self.unique_id.casefold()):
                self.counts['TIKTOK_BROADCASTER_COMMENTS_IGNORED']+=1
                self._log('BROADCASTER_COMMENT_IGNORED');return
            common=getattr(event,'common',None)
            ident=getattr(common,'msg_id',None)
            stamp=getattr(common,'create_time',None)
            stamp=stamp if type(stamp) in (int,float) and stamp>0 else None
            # SDK common.create_time is epoch seconds; unknown formats not invented.
            if stamp and self.session_started_at and stamp < self.session_started_at-1:
                self.counts['TIKTOK_REAL_EVENTS_REJECTED']+=1;self._log('TIKTOK_REAL_HISTORY_DROPPED');return
            uid=getattr(user,'id',None)
            author_id=public_string(handle,256) or (str(uid) if type(uid) is int and uid>0 else None)
            raw={'event_type':EVENTS[kind][1],
                'event_id':str(ident) if type(ident) in (int,str) and ident not in (0,'','0') else None,
                'author_id':author_id,'author_name':public_name(getattr(user,'nickname',None)) or public_name(handle) or None,
                'timestamp':stamp,'t0_event_received':self.clock()}
            if kind=='COMMENT':raw['text']=getattr(event,'content',None)
            if kind=='LIKE':
                count=getattr(event,'count',None)
                if type(count) is int and count>=0:raw['like_count']=count
            if kind=='GIFT':
                raw['gift_type']=public_string(getattr(getattr(event,'gift',None),'name',None),128)
                count=getattr(event,'repeat_count',None)
                raw['gift_quantity']=count if type(count) is int and count>0 else None
                # Streak frames are cumulative; only final frame enters batching.
                if getattr(event,'streaking',False) is True:
                    self.counts['TIKTOK_REAL_GIFT_STREAK_FRAMES']+=1;return
            if len(self._queue)>=500:
                self.counts['TIKTOK_REAL_EVENTS_REJECTED']+=1;self._log('TIKTOK_REAL_QUEUE_FULL');return
            self._queue.append(raw);self._log('TIKTOK_REAL_'+kind)

    async def _session(self,generation):
        self._loop=asyncio.get_running_loop();self._task=asyncio.current_task()
        def async_error(_loop,context):
            self._error(context.get('exception') or RuntimeError())
            if self._task:self._task.cancel()
        self._loop.set_exception_handler(async_error)
        try:
            factory,events=self._load()
            # SDK consults these environment variables implicitly. Fail closed;
            # never read/log their values or use an ambient signing credential.
            if any(key in os.environ for key in ('SIGN_API_KEY','SIGN_API_URL')):
                self._state_set('AUTH_REQUIRED','AMBIENT_SIGN_CONFIGURATION_BLOCKED');return
            self._client=factory(unique_id=self.unique_id,web_kwargs={'httpx_kwargs':{
                'trust_env':False,'event_hooks':{'response':[guard_json_response]}}})
            self._client.logger.disabled=True
            if self._stopping.is_set():return
            async def connected(event):
                observed=getattr(event,'unique_id',None)
                if not isinstance(observed,str) or observed.removeprefix('@').casefold()!=self.unique_id.casefold():
                    self._state_set('ERROR','BROADCASTER_MISMATCH');self._task.cancel();return
                self.session_started_at=self.wall_clock();self._state_set('CONNECTED')
            async def disconnected(event):
                if self._state in ('CONNECTED','CONNECTING'):self._state_set('DISCONNECTED')
            self._client.add_listener(events.ConnectEvent,connected)
            self._client.add_listener(events.DisconnectEvent,disconnected)
            for kind,(class_name,_,cap) in EVENTS.items():
                cls=getattr(events,class_name,None);self._caps[cap]=cls is not None
                if cls is not None:
                    async def handler(event,kind=kind):self._receive(kind,event,generation)
                    self._client.add_listener(cls,handler)
            self._state_set('CONNECTING')
            # start() returns the websocket task without connect()'s nested-loop
            # cleanup on cancellation in SDK 7.0.1. Ignore handshake history.
            task=await asyncio.wait_for(self._client.start(process_connect_events=False,
                fetch_room_info=False,fetch_gift_info=False,fetch_live_check=True,room_id=self.room_id),timeout=30)
            await task
            if self._state in ('CONNECTED','CONNECTING'):self._state_set('DISCONNECTED')
        except asyncio.CancelledError:pass
        except Exception as error:self._error(error)
        finally:
            if self._client:
                try:await asyncio.wait_for(self._client.disconnect(close_client=False),timeout=5)
                except (Exception,asyncio.CancelledError):pass
                try:await self._client.web.httpx_client.aclose()
                except Exception:pass
                try:await self._client.web.signer.client.aclose()
                except Exception:pass
            with self._lock:self._queue.clear()

    def _error(self,error):
        diagnostic=error_diagnostic(error);category=diagnostic['category']
        if category=='RATE_LIMITED':
            retry_value=next((row.get('retry_after') for row in diagnostic['responses'] if row.get('status')==429),None)
            delay=parse_retry_after(retry_value,self.wall_clock())
            self.retry_after=self.clock()+(delay if delay is not None else 60.)
        state=category if category in ('LIVE_OFFLINE','AUTH_REQUIRED','RATE_LIMITED') else 'ERROR'
        self._state_set(state,category)
        self._log('TIKTOK_REAL_ERROR | '+category+' | '+type(error).__name__)
        if diagnostic['exception']=='JSONDecodeError' or diagnostic['responses']:
            try:
                self.diagnostic_directory.mkdir(parents=True,exist_ok=True)
                target=self.diagnostic_directory/('tiktok-diagnostic-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())+'-'+str(time.time_ns()%1000000)+'.json')
                diagnostic.update({'source':'TikTokLive','broadcaster':'@'+self.unique_id,
                    'python':__import__('sys').version.split()[0],'sdk_version':version('TikTokLive')})
                target.write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
                self._last_diagnostic_path=target
                summary=','.join(str(row['status'])+'/'+str(row['content_type']) for row in diagnostic['responses']) or 'sem resposta HTTP observável'
                self._log('TIKTOK_REAL_DIAGNOSTIC | '+target.name+' | '+summary)
            except OSError:
                self._log('TIKTOK_REAL_DIAGNOSTIC | arquivo indisponível; diagnóstico sanitizado preservado em memória')

    def _run(self,generation):
        # HTTP/WS libraries may log signed URLs at INFO/DEBUG. Suppress only
        # this transport thread, preserving logging in the Gemini/UI threads.
        filt=_TransportLogFilter(threading.get_ident())
        loggers=[logging.getLogger(name) for name in ('httpx','httpcore','httpcore.connection','httpcore.http11','httpcore.http2','websockets.client','websockets.protocol')]
        for logger in loggers:logger.addFilter(filt)
        try:
            while not self._stopping.is_set() and generation==self._generation:
                self._session_runner(generation)
                with self._lock:
                    self._loop=None;self._task=None;self._client=None
                    transient=(self._state=='DISCONNECTED' or
                        (self._state=='ERROR' and self._reason=='CONNECTION_FAILED'))
                if not transient or self._stopping.is_set() or self._reconnects>=self.max_reconnects:break
                self._reconnects+=1
                delay=min(8,2**self._reconnects)
                self._log('TIKTOK_REAL_RECONNECT | '+str(self._reconnects)+'/'+str(self.max_reconnects))
                if self._stopping.wait(delay):break
        finally:
            for logger in loggers:logger.removeFilter(filt)
            with self._lock:self._loop=None;self._task=None;self._client=None
            _lease.release()
