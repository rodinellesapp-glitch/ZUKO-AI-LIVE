"""Bounded RAM-only session metadata. No conversation storage, IO or model access."""
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
import hashlib
import re
import threading
import time
import unicodedata
import uuid
from live_trends import TrendClusters


@dataclass(frozen=True)
class MemoryConfig:
    max_topics: int = 64
    max_questions: int = 500
    max_events: int = 200
    max_participants: int = 200
    max_highlights: int = 100
    max_recent: int = 64
    max_ids: int = 2000
    history_ttl: float = 14400
    participant_ttl: float = 7200
    recent_answer: float = 300
    trending_window: float = 300
    trending_authors: int = 5
    starting_seconds: float = 300
    early_seconds: float = 1200
    active_seconds: float = 3600


def normalize(text):
    text = unicodedata.normalize('NFKD', str(text).casefold())
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(c for c in text if not unicodedata.combining(c))))


# Only these public subject labels can enter shared context, never free-form topics.
TOPICS = {'python': {'python'}, 'robotica': {'robotica', 'robo', 'arduino'},
          'celular': {'celular', 'smartphone', 'telefone'}, 'gemini': {'gemini'},
          'programacao': {'programacao', 'codigo', 'linguagem'},
          'arquitetura_jarvis': {'jarvis', 'arquitetura'}}


class LiveSessionMemory:
    def __init__(self, clock=time.monotonic, config=None):
        self.clock, self.config = clock, config or MemoryConfig()
        self.lock = threading.RLock()
        self.logs = deque(maxlen=200)
        self.reset()

    def reset(self):
        with self.lock:
            c = self.config
            self.session_id = uuid.uuid4().hex
            self.started_at = self.clock()
            self.current_topic = 'geral'
            self.discussed_topics, self.answered_questions = OrderedDict(), OrderedDict()
            self.participant_activity, self.key_events = OrderedDict(), OrderedDict()
            self.previous_topics = deque(maxlen=c.max_recent)
            self.topic_transitions = deque(maxlen=c.max_recent)
            self.recent_interventions = deque(maxlen=c.max_recent)
            self.recent_presenter_topics = deque(maxlen=c.max_recent)
            self.session_highlights = deque(maxlen=c.max_highlights)
            self.engagement_history = deque(maxlen=100)
            self.reaction_history = deque(maxlen=100)
            self._asked, self._seen, self._answered_ids = OrderedDict(), OrderedDict(), OrderedDict()
            self._topic_asked = OrderedDict()
            if hasattr(self, "trends"):
                self.trends.groups.clear(); self.trends.counts.clear(); self.trends.logs.clear()
            else:
                self.trends = TrendClusters(self.clock)
            self.counts = Counter()
            self.logs.clear(); self.logs.append('LIVE_MEMORY_RESET')

    def _fingerprint(self, value):
        return hashlib.blake2s(str(value).encode('utf-8'), key=self.session_id.encode(), digest_size=12).hexdigest()

    @staticmethod
    def _bound(mapping, maximum):
        while len(mapping) > maximum: mapping.popitem(last=False)

    def _prune(self):
        now, c = self.clock(), self.config
        for mapping, ttl, field in ((self.participant_activity,c.participant_ttl,'last_seen'),
                (self.discussed_topics,c.history_ttl,'last_seen'),
                (self.answered_questions,c.history_ttl,'last_answered_at'),
                (self.key_events,c.history_ttl,'timestamp')):
            for key, record in list(mapping.items()):
                if now-record[field] >= ttl: del mapping[key]
        for history in (self.previous_topics,self.topic_transitions,self.recent_interventions,
                        self.recent_presenter_topics,self.session_highlights):
            while history and now-history[0]['timestamp'] >= c.history_ttl: history.popleft()
        for mapping in (self._asked, self._topic_asked):
            for key, authors in list(mapping.items()):
                for author, at in list(authors.items()):
                    if now-at >= c.trending_window: del authors[author]
                if not authors: del mapping[key]
        if self.current_topic not in self.discussed_topics: self.current_topic='geral'

    def describe(self, text):
        norm = normalize(text)
        words = set(norm.split())
        language = (('jarvis' in words and bool(words & {'linguagem','python'})) or
                    norm in {'ele foi feito em python','que linguagem voces usam'})
        topic = 'arquitetura_jarvis' if language else next((k for k,v in TOPICS.items() if words & v),'geral')
        question = bool('?' in str(text) or re.match(r'^(qual|quais|como|por que|onde|quando|que linguagem|ele foi feito)\b',norm))
        key = 'jarvis_linguagem' if language else self._fingerprint(norm)
        return topic, key, question

    def _participant(self, author):
        key, now = self._fingerprint(author), self.clock()
        item = self.participant_activity.setdefault(key, dict(author_id=key,first_seen=now,last_seen=now,
            message_count=0,selected_count=0,answered_count=0,event_count=0))
        item['last_seen']=now; self.participant_activity.move_to_end(key)
        self._bound(self.participant_activity,self.config.max_participants)
        return key,item

    def observe(self, message_id, author, text):
        with self.lock:
            self._prune()
            ident=self._fingerprint(message_id)
            if ident in self._seen: return self.lookup(text)
            self._seen[ident]=None; self._bound(self._seen,self.config.max_ids)
            author_key, participant=self._participant(author); participant['message_count']+=1
            topic,qkey,question=self.describe(text); now=self.clock()
            if topic != 'geral':
                old=self.discussed_topics.get(topic)
                if old is None:
                    old=dict(topic_key=topic,first_seen=now,last_seen=now,mentions=0,answered_count=0)
                    self.discussed_topics[topic]=old; self.logs.append('LIVE_MEMORY_TOPIC_ADDED')
                if topic != self.current_topic:
                    if old['mentions']:
                        self.counts['LIVE_MEMORY_TOPIC_RETURNS']+=1; self.logs.append('LIVE_MEMORY_TOPIC_RETURN')
                    if self.current_topic != 'geral': self.previous_topics.append(dict(topic_key=self.current_topic,timestamp=now))
                    self.topic_transitions.append(dict(topic_key=topic,timestamp=now))
                    self.current_topic=topic
                    self.record_event('TOPIC_SHIFT',message_id,topic=topic)
                old['last_seen']=now; old['mentions']+=1
                self.discussed_topics.move_to_end(topic); self._bound(self.discussed_topics,self.config.max_topics)
            if question:
                authors=self._asked.setdefault(qkey,OrderedDict()); authors[author_key]=now
                authors.move_to_end(author_key); self._bound(authors,self.config.max_participants)
                self._asked.move_to_end(qkey); self._bound(self._asked,self.config.max_questions)
                topic_authors = self._topic_asked.setdefault(topic, OrderedDict())
                previous_count = len(topic_authors)
                topic_authors[author_key] = now; topic_authors.move_to_end(author_key)
                self._bound(topic_authors,self.config.max_participants)
                self._topic_asked.move_to_end(topic); self._bound(self._topic_asked,self.config.max_topics)
                if previous_count < self.config.trending_authors <= len(topic_authors):
                    self.session_highlights.append(dict(type='HIGH_ENGAGEMENT',timestamp=now,topic_key=topic))
            result=self.lookup(text)
            if result['status'] in {'ANSWERED_RECENTLY','ANSWERED_LONG_AGO','TRENDING_AGAIN'}:
                self.counts['LIVE_MEMORY_REPEAT_HITS']+=1; self.logs.append('LIVE_MEMORY_REPEAT_HIT')
            if result['status']=='TRENDING_AGAIN':
                self.record_event('TRENDING_QUESTION',qkey+str(int(now//self.config.trending_window)),topic=topic)
            return result

    def selected(self, author):
        with self.lock: self._participant(author)[1]['selected_count']+=1

    def lookup(self, text):
        with self.lock:
            self._prune(); topic,key,question=self.describe(text)
            answer=self.answered_questions.get(key) if question else None
            count=len(self._asked.get(key,{})); status='NEW'
            if self.discussed_topics.get(topic, {}).get('mentions',0)>1: status='ALREADY_DISCUSSSED'
            if answer:
                status='ANSWERED_RECENTLY' if self.clock()-answer['last_answered_at']<self.config.recent_answer else 'ANSWERED_LONG_AGO'
                if count>=self.config.trending_authors: status='TRENDING_AGAIN'
            return dict(status=status,topic_key=topic,question_key=key,unique_authors=count,
                        last_answered_at=answer['last_answered_at'] if answer else None)

    def topic_info(self, topic):
        with self.lock:
            self._prune(); item=self.discussed_topics.get(topic)
            return {'discussed_recently':bool(item and self.clock()-item['last_seen']<self.config.recent_answer),
                    'unique_authors':len(self._topic_asked.get(topic,{})),
                    'mentions':item['mentions'] if item else 0}

    def answered(self, message_id, author, text, session_id=None):
        with self.lock:
            if session_id is not None and session_id!=self.session_id: return
            self._prune(); ident=self._fingerprint(message_id)
            if ident in self._answered_ids: return
            self._answered_ids[ident]=None; self._bound(self._answered_ids,self.config.max_ids)
            author_key,p=self._participant(author); p['answered_count']+=1
            topic,key,question=self.describe(text); now=self.clock()
            self.recent_interventions.append(dict(topic_key=topic,timestamp=now))
            if topic in self.discussed_topics: self.discussed_topics[topic]['answered_count']+=1
            if not question: return
            item=self.answered_questions.setdefault(key,dict(question_key=key,topic_key=topic,answered_at=now,
                last_answered_at=now,answer_count=0,unique_authors=OrderedDict()))
            item['status']='INDIVIDUAL_ANSWERED'
            item['last_answered_at']=now; item['answer_count']+=1; item['unique_authors'][author_key]=None
            self._bound(item['unique_authors'],self.config.max_participants)
            self.answered_questions.move_to_end(key); self._bound(self.answered_questions,self.config.max_questions)
            self.logs.append('LIVE_MEMORY_QUESTION_ANSWERED')

    def record_event(self, kind, event_id, author=None, topic='geral'):
        with self.lock:
            if kind not in {'SUPER_CHAT','MEMBER','MEMBERSHIP','GIFT','TRENDING_QUESTION','TOPIC_SHIFT','PRESENTER_INTERVENTION'}: return
            topic=topic if topic in TOPICS else 'geral'
            ident=self._fingerprint(kind+str(event_id))
            if ident in self.key_events: return
            item=dict(type=kind,timestamp=self.clock(),topic_key=topic,identifier=ident)
            self.key_events[ident]=item; self._bound(self.key_events,self.config.max_events)
            if author: self._participant(author)[1]['event_count']+=1
            if kind in {'TRENDING_QUESTION','SUPER_CHAT','GIFT'}:
                self.session_highlights.append(dict(type=kind,timestamp=self.clock(),topic_key=topic))
            self.logs.append('LIVE_MEMORY_EVENT')

    def presenter_repeated(self, topic):
        with self.lock:
            self._prune()
            return (self.discussed_topics.get(topic,{}).get('answered_count',0)>=3 or
                    any(x['topic_key']==topic for x in self.recent_presenter_topics))

    def presenter_spoken(self, ident, topic, session_id=None):
        with self.lock:
            if session_id is not None and session_id!=self.session_id: return
            topic=topic if topic in TOPICS else 'geral'
            item=dict(topic_key=topic,timestamp=self.clock())
            self.recent_presenter_topics.append(item); self.recent_interventions.append(item.copy())
            self.record_event('PRESENTER_INTERVENTION',ident,topic=topic)

    def recap(self):
        with self.lock:
            self._prune(); self.counts['LIVE_MEMORY_RECAPS']+=1
            return dict(topics=list(self.discussed_topics)[-3:],events=dict(Counter(x['type'] for x in self.key_events.values())))

    def record_engagement(self, action, topic):
        with self.lock:
            self.engagement_history.append({'action':action,'topic':topic,'timestamp':self.clock()})

    def record_reaction(self, category):
        with self.lock:
            self.reaction_history.append({'category':category,'timestamp':self.clock()})

    def phase(self):
        age=self.clock()-self.started_at; c=self.config
        return 'STARTING' if age<c.starting_seconds else 'EARLY' if age<c.early_seconds else 'ACTIVE' if age<c.active_seconds else 'LONG_RUNNING'

    def prompt_hint(self, text):
        with self.lock:
            info=self.lookup(text)
            if info['last_answered_at'] is None: return ''
            age=int(self.clock()-info['last_answered_at'])
            return (f"SESSION_TOPIC_HISTORY={info['topic_key']}; QUESTION_ALREADY_ANSWERED=SIM; "
                    f"LAST_TOPIC_DISCUSSION={age}s; SESSION_PROGRESS={self.phase()}. "
                    "Resuma ou aprofunde sem dizer 'já respondi'.")[:280]

    def snapshot(self):
        with self.lock:
            self._prune()
            return {**{key:self.counts[key] for key in ('LIVE_MEMORY_REPEAT_HITS','LIVE_MEMORY_RECAPS','LIVE_MEMORY_TOPIC_RETURNS')},
                'LIVE_MEMORY_TOPICS':len(self.discussed_topics),'LIVE_MEMORY_QUESTIONS':len(self.answered_questions),
                'LIVE_MEMORY_EVENTS':len(self.key_events),'LIVE_MEMORY_PARTICIPANTS':len(self.participant_activity),
                'LIVE_MEMORY_HIGHLIGHTS':len(self.session_highlights),'LIVE_MEMORY_SESSION_AGE':max(0,self.clock()-self.started_at),
                'LIVE_MEMORY_CURRENT_TOPIC':self.current_topic,'LIVE_MEMORY_PHASE':self.phase()}

    def drain_logs(self):
        with self.lock:
            result=list(self.logs); self.logs.clear(); return result
