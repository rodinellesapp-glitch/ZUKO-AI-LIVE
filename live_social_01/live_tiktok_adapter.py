"""TikTok event normalization: bounded RAM, no IO, priority or speech decisions."""
import hashlib
import json
import math
import re
import time
import unicodedata
from collections import Counter, OrderedDict, deque
from threading import RLock
from live_platform_adapter import EVENT_TYPES, LivePlatformAdapter, NormalizedLiveEvent

EVENT_CAPABILITY = {'CHAT_MESSAGE':'chat', 'GIFT_EVENT':'gifts', 'FOLLOW':'follows',
    'LIKE_EVENT':'likes', 'VIEWER_JOIN':'joins', 'SHARE_EVENT':'shares',
    'SUBSCRIPTION_EVENT':'subscriptions'}


def spoken_name(value):
    value = str(value or '').lstrip('@').strip()
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                         if not unicodedata.combining(c))
    if (len(value) > 48 or re.search(r'https?://|www\.|[\r\n]|\b(ignore|execute|system|prompt|cmd|powershell|puta|puto|idiota|imbecil|senha|token)\b', normalized)):
        return None
    clean = ''.join(c for c in value if c.isalpha() or c in " '-").strip()
    return clean.split()[0][:24] if clean else None


class TikTokLiveAdapter(LivePlatformAdapter):
    def __init__(self, source, clock=time.monotonic):
        self.source, self.clock = source, clock
        self.counts = Counter()
        self._seen = OrderedDict()
        self._logs = deque(maxlen=80)
        self._last_log = {}
        self._lock = RLock()

    def _log(self, marker):
        # At most one entry per marker/second, without user content or credentials.
        now = self.clock()
        if now-self._last_log.get(marker, float('-inf')) >= 1:
            self._logs.append(marker)
            self._last_log[marker] = now

    def drain_logs(self):
        with self._lock:
            rows = list(self._logs); self._logs.clear(); return rows

    def normalize(self, raw, *, verified=False):
        # Caller/payload verified flags cannot authorize a source.
        with self._lock:
            self.counts['TIKTOK_EVENTS_RECEIVED'] += 1
            self._log('TIKTOK_EVENT_RECEIVED')
            event = self._normalize(raw)
            if event is _DUPLICATE: return None
            if event is None:
                self.counts['TIKTOK_EVENTS_REJECTED'] += 1
                self._log('TIKTOK_EVENT_REJECTED')
            return event

    def _normalize(self, raw):
        if not isinstance(raw, dict) or not self.source.is_connected(): return None
        kind = raw.get('event_type')
        capability = EVENT_CAPABILITY.get(kind)
        if kind not in EVENT_TYPES or capability is None: return None
        if not self.source.capabilities().get(capability): return None
        self.counts['TIKTOK_'+capability.upper()+'_RECEIVED'] += 1
        strings = ('event_id','author_id','author_name','text','gift_type')
        limits = (256,256,512,1000,128)
        for key, limit in zip(strings, limits):
            value = raw.get(key)
            if value is not None and (not isinstance(value,str) or len(value)>limit): return None
        if kind=='CHAT_MESSAGE' and (not raw.get('text') or not (raw.get('author_id') or raw.get('author_name'))): return None
        stamp, qty, value = raw.get('timestamp'), raw.get('gift_quantity'), raw.get('gift_value')
        if stamp is not None and (isinstance(stamp,bool) or not isinstance(stamp,(str,int,float))
                or isinstance(stamp,(int,float)) and not math.isfinite(stamp)
                or isinstance(stamp,str) and len(stamp)>64): return None
        if qty is not None and (type(qty) is not int or not 1<=qty<=1000000): return None
        if value is not None and (type(value) not in (int,float,str) or
                isinstance(value,(int,float)) and (not math.isfinite(value) or value<0) or
                isinstance(value,str) and len(value)>64): return None
        now = self.clock()
        ident = raw.get('event_id')
        fingerprint = not bool(ident)
        if fingerprint:
            fields = {k:raw.get(k) for k in (*strings[1:], 'event_type','timestamp','gift_quantity','gift_value')}
            ident = 'fingerprint:'+hashlib.sha256(json.dumps(fields,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:32]
        for key, (at, fallback) in list(self._seen.items()):
            if fallback and now-at>=3: del self._seen[key]
        if ident in self._seen:
            self.counts['TIKTOK_EVENTS_DUPLICATE'] += 1
            self._log('TIKTOK_EVENT_DUPLICATE')
            # Duplicate is distinct from malformed/rejected input.
            return _DUPLICATE
        self._seen[ident] = (now,fingerprint)
        while len(self._seen)>10000: self._seen.popitem(last=False)
        # Only allow structural evidence. Never persist arbitrary session/token metadata.
        metadata = {k:raw[k] for k in ('high','special') if type(raw.get(k)) is bool}
        metadata['internal_fingerprint'] = fingerprint
        metadata['simulation'] = bool(self.source.simulation)
        arrival=now
        if self.source.name=='TIKTOKLIVE':
            t0=raw.get('t0_event_received')
            if type(t0) in (int,float) and math.isfinite(t0) and t0<=now:
                metadata['T0_EVENT_RECEIVED']=t0
                arrival=t0
            metadata['T1_NORMALIZED']=now
            count=raw.get('like_count')
            if type(count) is int and count>=0:metadata['like_count']=count
        real = self.source.verified is True and not self.source.simulation
        author_name = raw.get('author_name')
        output_id = ident+':'+str(int(now*1000)) if fingerprint else ident
        event = NormalizedLiveEvent(platform='TIKTOK',event_type=kind,event_id=output_id,
            author_id=raw.get('author_id'),author_name=author_name,text=raw.get('text'),
            gift_type=raw.get('gift_type'),gift_quantity=qty,timestamp=stamp,
            gift_value=value,metadata=metadata,source_verified=real,source_name=self.source.name,
            received_at=arrival,display_name=author_name,spoken_name=spoken_name(author_name))
        self.counts['TIKTOK_EVENTS_NORMALIZED'] += 1
        self._log('TIKTOK_EVENT_NORMALIZED')
        if kind=='GIFT_EVENT' and real: self._log('TIKTOK_GIFT_CONFIRMED')
        return event

    def read_event(self):
        raw = self.source.read_event()
        if raw is None: return None
        event = self.normalize(raw)
        return None if event is _DUPLICATE else event

    def snapshot(self):
        with self._lock:
            state = self.source.health()['connection']; caps = self.source.capabilities()
            result = {'PLATFORM':'TIKTOK','TIKTOK_SOURCE':self.source.name,'TIKTOK_CONNECTION':state}
            health=self.source.health()
            if self.source.name=='TIKTOKLIVE':
                result['SOURCE']=self.source.name
                result['BROADCASTER']=health.get('broadcaster','—')
                result['TIKTOK_REASON']=health.get('reason') or '—'
                for cap,validation in health.get('capability_validation',{}).items():
                    result['TIKTOK_'+cap.upper()+'_VALIDATION']=validation
                result.update(health.get('counts',{}))
            for cap in ('chat','gifts','follows','likes','joins','shares'):
                result['TIKTOK_'+cap.upper()] = ('SIMULATOR' if self.source.simulation and state=='SIMULATOR'
                    else 'ONLINE' if state in ('ONLINE','CONNECTED') and self.source.verified else 'OFFLINE') if caps.get(cap) else 'INDISPONÍVEL'
            for key in ('EVENTS_RECEIVED','CHAT_RECEIVED','GIFTS_RECEIVED','FOLLOWS_RECEIVED',
                'LIKES_RECEIVED','JOINS_RECEIVED','SHARES_RECEIVED','EVENTS_NORMALIZED','EVENTS_REJECTED','EVENTS_DUPLICATE'):
                result['TIKTOK_'+key] = self.counts['TIKTOK_'+key]
            if self.source.name=='TIKTOKLIVE':
                for key in ('EVENTS_NORMALIZED','EVENTS_REJECTED','EVENTS_DUPLICATE'):
                    result['TIKTOK_REAL_'+key]=self.counts['TIKTOK_'+key]+health.get('counts',{}).get('TIKTOK_REAL_'+key,0)
            return result


_DUPLICATE = object()
