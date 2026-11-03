"""RAM-only ZUKO conversation memory with per-participant isolation and TTL."""
from collections import OrderedDict, deque
import re
import threading
import time
import unicodedata


HISTORY_TTL_SECONDS = 15 * 60
MAX_PARTICIPANT_TURNS = 6
MAX_PARTICIPANTS = 100
PUBLIC_CONTEXT_TURNS = 6


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text or '').casefold()) if not unicodedata.combining(c))


def private_safe(text):
    text=re.sub(r'https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d[\d .()-]{7,}\d','[dado privado]',str(text or ''))
    return re.sub(r'[\x00-\x1f]',' ',text).strip()[:240]


class Conversation:
    def __init__(self,clock=time.monotonic,*,ttl_seconds=HISTORY_TTL_SECONDS,
                 max_participants=MAX_PARTICIPANTS,turns_per_participant=MAX_PARTICIPANT_TURNS,
                 public_context_turns=PUBLIC_CONTEXT_TURNS):
        self.clock=clock;self.lock=threading.RLock()
        self.ttl_seconds=max(1.0,float(ttl_seconds))
        self.max_participants=max(1,int(max_participants))
        self.turns_per_participant=max(1,int(turns_per_participant))
        self.public_context_turns=max(1,int(public_context_turns))
        self.turns=OrderedDict()
        self.recent=deque(maxlen=self.public_context_turns)

    def clear(self):
        with self.lock:self.turns.clear();self.recent.clear()

    def _prune(self,now):
        for key,history in list(self.turns.items()):
            while history and now-history[0][0]>=self.ttl_seconds:
                history.popleft()
            if not history:del self.turns[key]
        while self.recent and now-self.recent[0][0]>=self.ttl_seconds:
            self.recent.popleft()
        while len(self.turns)>self.max_participants:
            self.turns.popitem(last=False)

    def context(self,event):
        with self.lock:
            now=self.clock();self._prune(now)
            key=getattr(event,'author_key',None) or getattr(event,'author_name','')
            return [{'comment':comment,'spoken_reply':reply} for _,comment,reply in self.turns.get(key,())]

    def recent_public_context(self):
        with self.lock:
            self._prune(self.clock())
            return [{'comment':comment,'spoken_reply':reply}
                    for _,_,comment,reply in self.recent]

    def requires_context_understanding(self,event):
        if not self.context(event):return False
        text=normalized(getattr(event,'text',''))
        return bool(re.match(r'^(e (para|pra|sobre|qual|como|por que|onde|quando|voce|esse|essa|isso|ele|ela)|e ai\b|como assim\b|mas e\b|entao\b|isso (significa|quer dizer|funciona|e verdade|foi|pode|tem)|essa ideia\b|esse caso\b|(?:explica|detalha) isso\b|o que voce (disse|falou|achou)|por que isso\b)',text))

    def delivered(self,event,text):
        if not event:return
        with self.lock:
            now=self.clock();self._prune(now);kind=getattr(event,'event_type','')
            comment=private_safe(getattr(event,'text',''))
            reply=private_safe(text)
            self.recent.append((now,kind,comment,reply))
            if kind=='CHAT_MESSAGE':
                key=getattr(event,'author_key',None) or getattr(event,'author_name','')
                history=self.turns.setdefault(key,deque(maxlen=self.turns_per_participant))
                history.append((now,comment,reply))
                self.turns.move_to_end(key)
                while len(self.turns)>self.max_participants:self.turns.popitem(last=False)
