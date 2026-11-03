"""Source boundary only. No TikTok endpoints, browser session or model calls."""
from abc import ABC, abstractmethod
from collections import deque
from threading import RLock

CAPABILITIES = ('chat', 'gifts', 'follows', 'likes', 'joins', 'shares', 'subscriptions')
SOURCE_TYPES = ('TIKTOK_OFFICIAL', 'TIKTOK_LOCAL_STUDIO', 'TIKTOK_SIMULATOR')


class TikTokEventSource(ABC):
    name = None
    verified = False
    simulation = False

    @abstractmethod
    def start(self): ...
    @abstractmethod
    def stop(self): ...
    @abstractmethod
    def is_connected(self): ...
    @abstractmethod
    def capabilities(self): ...
    @abstractmethod
    def health(self): ...
    @abstractmethod
    def read_event(self): ...


class UnavailableTikTokSource(TikTokEventSource):
    """No real implementation until a legitimate event interface is proved."""
    def __init__(self, name='TIKTOK_LOCAL_STUDIO'):
        if name not in SOURCE_TYPES[:2]: raise ValueError('Unknown real source')
        self.name = name
    def start(self): return False
    def stop(self): pass
    def is_connected(self): return False
    def capabilities(self): return dict.fromkeys(CAPABILITIES, False)
    def health(self):
        return {'connection': 'INDISPONÍVEL', 'reason': 'TIKTOK SOURCE UNAVAILABLE',
                'source': self.name, 'verified': False}
    def read_event(self): return None


class TikTokSimulatorSource(TikTokEventSource):
    """Explicit, bounded, thread-safe RAM fixtures. Never claims a real connection."""
    name = 'TIKTOK_SIMULATOR'
    simulation = True

    def __init__(self, capabilities=None):
        self._caps = {k: True for k in CAPABILITIES}
        if capabilities is not None:
            self._caps = {k: capabilities.get(k) is True for k in CAPABILITIES}
        self._events = deque()
        self._connected = False
        self._lock = RLock()

    def start(self):
        with self._lock: self._connected = True
        return True
    def stop(self):
        with self._lock:
            self._connected = False
            self._events.clear()  # Never replay an offline backlog on recovery.
    def is_connected(self):
        with self._lock: return self._connected
    def capabilities(self): return dict(self._caps)
    def health(self):
        return {'connection': 'SIMULATOR' if self.is_connected() else 'OFFLINE',
                'source': self.name, 'verified': False}
    def push(self, event):
        with self._lock:
            if not self._connected or len(self._events) >= 500: return False
            self._events.append(dict(event))
            return True
    def read_event(self):
        with self._lock:
            return self._events.popleft() if self._connected and self._events else None
