"""Internal platform contract only. No clients, endpoints, credentials or IO."""
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

EVENT_TYPES=frozenset(('CHAT_MESSAGE','VIEWER_JOIN','FOLLOW','LIKE_EVENT','GIFT_EVENT',
    'SHARE_EVENT','SUBSCRIPTION_EVENT','PLATFORM_EVENT'))

def safe_name(value):
    value=re.sub(r'^@+','',str(value or '')).strip()
    clean=''.join(c for c in unicodedata.normalize('NFKD',value.lower()) if not unicodedata.combining(c))
    if re.search(r'\b(idiota|imbecil|puta|puto|pinto|penis|vagina|buceta|ignore|execute|cmd|powershell)\b',clean):return ''
    if not 1<=len(value)<=32 or not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .'-]*",value):return ''
    return value.split()[0]

@dataclass(frozen=True)
class PlatformEvent:
    platform: str
    event_type: str
    event_id: str
    author_id: str=''
    author_name: str=''
    text: str=''
    gift_type: str=''
    gift_quantity: int | None=None
    timestamp: float | str | None=None
    raw_metadata: dict=field(default_factory=dict)
    confirmed: bool=False
    priority: str='NORMAL'

@dataclass(frozen=True)
class NormalizedLiveEvent(PlatformEvent):
    """Extended contract; legacy positional PlatformEvent callers stay unchanged.

    confirmed is the legacy pipeline evidence flag, not proof of a real source.
    Simulator evidence may exercise the pipeline only in explicitly labelled tests.
    """
    gift_value: object=None
    metadata: dict=field(default_factory=dict)
    source_verified: bool=False
    source_name: str | None=None
    received_at: float | None=None
    display_name: str | None=None
    spoken_name: str | None=None

class LivePlatformAdapter(ABC):
    @abstractmethod
    def normalize(self,raw,*,verified=False):raise NotImplementedError

class NormalizedPlatformAdapter(LivePlatformAdapter):
    """The future connector must supply verified=True for authenticated event types."""
    def __init__(self,platform):self.platform=platform
    def normalize(self,raw,*,verified=False):
        kind=str(raw.get('event_type','')).upper();ident=str(raw.get('event_id',''))[:256]
        if kind not in EVENT_TYPES or not ident:return None
        stamp=raw.get('timestamp')
        if stamp is not None and not isinstance(stamp,(str,int,float)):return None
        if isinstance(stamp,str):stamp=stamp[:64]
        quantity=raw.get('gift_quantity')
        if quantity is not None and (type(quantity) is not int or not 1<=quantity<=1000000):return None
        # Whitelist metadata; never retain a connector's raw cookie/token/session payload.
        metadata={k:raw[k] for k in ('high','special') if type(raw.get(k)) is bool}
        return PlatformEvent(self.platform,kind,ident,str(raw.get('author_id',''))[:128],
            str(raw.get('author_name',''))[:128],str(raw.get('text',''))[:1000],
            str(raw.get('gift_type',''))[:64],quantity,stamp,metadata,bool(verified),
            'HIGH' if verified and (raw.get('high') is True or raw.get('special') is True) else 'NORMAL')

class TikTokContractAdapter(NormalizedPlatformAdapter):
    def __init__(self):super().__init__('tiktok')

class YouTubePlatformAdapter(NormalizedPlatformAdapter):
    def __init__(self):super().__init__('youtube')
    def chat(self,comment):
        return PlatformEvent('youtube','CHAT_MESSAGE',comment.comment_id,comment.author,comment.author,
            comment.text,timestamp=getattr(comment,'received_at',None))
    def live_event(self,event):
        mapping={'GIFT':'GIFT_EVENT','SUPER_CHAT':'PLATFORM_EVENT','DONATION':'PLATFORM_EVENT',
            'MEMBER':'SUBSCRIPTION_EVENT','MEMBERSHIP':'SUBSCRIPTION_EVENT','LIKE':'LIKE_EVENT','SUBSCRIBE':'FOLLOW'}
        return PlatformEvent(event.platform,mapping.get(event.event_type,'PLATFORM_EVENT'),event.event_id,
            event.author_id or '',event.author_name or '',event.message or '',event.gift_name or '',
            event.count,event.timestamp,{},True,event.priority)
