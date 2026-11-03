"""Bounded, deterministic audience selection before the response pipeline."""
from __future__ import annotations
import re, time, unicodedata
from collections import Counter, deque, defaultdict
from dataclasses import dataclass
from live_trends import TrendClusters
from live_reactions import reaction_only, reaction_comment
from live_cohost import current_intent

CONFIG = {"calm": 8, "normal": 20, "busy": 40, "ttl": 45, "fairness": 35,
          "similarity": .55, "trending_authors": 3, "recent_answered": 90, "spam_repeat": 3}

@dataclass
class AudienceItem:
    message_id: str; author_id: str; classification: str; received_at: float
    priority: int; score: int; topic_key: str; event_type: str = "CHAT"; conversation_version: int = 0
    presenter_answer: dict | None = None

def key(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return set(re.findall(r"[a-z0-9]{3,}", text)) - {"qual", "como", "voce", "jarvis", "para"}


def flow_priority(flow_decision) -> int:
    """Keep relevant questions and explicit follow-ups out of low-value trend suppression."""
    if not flow_decision:return 1
    action=getattr(flow_decision,'action','')
    score=getattr(flow_decision,'score',0)
    return 3 if score>=35 or action in {
        'ANSWER','DEEP_ANSWER','CONTINUE_THREAD','CURIOUS_FOLLOWUP','JOKE','PLAY_ALONG','PASS_TO_HOST'} else 1

class LiveAudienceManager:
    def __init__(self, clock=time.monotonic, config=None, session_memory=None) -> None:
        self.session_memory = session_memory
        self.clock, self.config = clock, {**CONFIG, **(config or {})}
        self.messages, self.authors, self.answered, self.selected = deque(), defaultdict(deque), deque(), deque()
        self.trends = session_memory.trends if session_memory else TrendClusters(clock, self.config["trending_authors"])
        self.groups = self.trends.groups
        self.last_reason = ""
        self.question_window=None
        self.last_selected = {}; self.topic = "geral"; self.counters = Counter()
        self.metrics = {"AUDIENCE_MODE":"CALM", "AUDIENCE_TOPIC":"geral"}

    def _mode(self, now):
        while self.messages and now-self.messages[0][0] > 60: self.messages.popleft()
        rate=len(self.messages); c=self.config
        mode="CALM" if rate<c["calm"] else "NORMAL" if rate<c["normal"] else "BUSY" if rate<c["busy"] else "VERY_BUSY"
        self.metrics.update({"AUDIENCE_CHAT_RATE":rate,"AUDIENCE_MODE":mode}); return mode

    def classify(self, author, text, moderation=None):
        if current_intent(text)=='JOKE_REQUEST':return 'CONTENT_REQUEST'
        if reaction_comment(text): return 'REACTION'
        norm=" ".join(text.casefold().split()); words=key(text)
        if re.fullmatch(r'k+[!. ]*', norm): return "REACTION"
        if moderation is None and (not norm or len(norm)>800 or re.search(r"https?://", norm) or len(re.findall(r"(.)\1{7,}",norm))): return "SPAM"
        if len(norm)<=4 and (not words or norm in {"kkkk","kkk","oi","ola","😂","😀"}): return "GREETING" if norm in {"oi","ola"} else "REACTION"
        if norm.count("😂")>=2 or norm.count("🔥")>=3: return "REACTION"
        if "jarvis" in norm or "?" in norm or re.match(r"^(qual|como|por que|porque|onde|quando)\b",norm): return "QUESTION"
        if re.match(r"^(e |sim$|nao$|não$|por que|como assim|me explica)",norm): return "FOLLOWUP"
        if re.search(r"\b(concordo|fala com|para o |pra o )\b",norm): return "COMMENT"
        return "UNKNOWN"

    def _topic(self, text):
        w=key(text)
        if w & {"python","codigo","linguagem","programacao"}: return "programacao"
        if w & {"robo","robotica","arduino","sensor"}: return "robotica"
        if w & {"celular","smartphone","telefone"}: return "celular"
        return self.topic

    def admit(self, message_id, author, text, event_type="CHAT", priority=1, moderation=None,
              local_safe_bypass=False, flow_decision=None):
        self.last_reason = ""
        self.metrics.pop("TREND_LAST_CLUSTER", None)
        if moderation is not None and not moderation.presenter_allowed:
            self.last_reason='MODERATION_BLOCKED'
            self.counters['AUDIENCE_MESSAGES_RECEIVED'] += 1
            self.counters['AUDIENCE_MESSAGES_SILENCED'] += 1
            if moderation.suppress: self.counters['AUDIENCE_SPAM_IGNORED'] += 1
            self.metrics.update(self.counters)
            return 'SILENCE', None
        if self.session_memory:
            memory_status = self.session_memory.observe(message_id, author, text)
            self.metrics['SESSION_MEMORY_STATUS'] = memory_status['status']
        now=self.clock(); self.messages.append((now,author,text)); self.counters["AUDIENCE_MESSAGES_RECEIVED"]+=1
        mode=self._mode(now); classification=self.classify(author,text,moderation)
        if flow_decision and flow_decision.action in {'CURIOUS_FOLLOWUP','PLAY_ALONG','PASS_TO_HOST'}:classification='COMMENT'
        if flow_decision and flow_decision.action=='PASS_TO_HOST':classification='QUESTION'
        if flow_decision and flow_decision.action=='CONTINUE_THREAD':classification='FOLLOWUP'
        answer=self.question_window.accept(message_id,author,text) if self.question_window and classification not in {'SPAM','CONTENT_REQUEST'} and not (reaction_comment(text) and not reaction_only(text)) else None
        if answer: classification='PRESENTER_ANSWER'
        history=self.authors[author]; history.append((now,text));
        while history and now-history[0][0]>20: history.popleft()
        if moderation is None and sum(1 for _, old in history if old.casefold()==text.casefold())>=self.config["spam_repeat"]:
            classification="SPAM"
        topic=self._topic(text); self.topic=topic; self.metrics["AUDIENCE_TOPIC"]=topic
        if answer:
            self.counters['PRESENTER_ANSWERS']+=1
            item=AudienceItem(message_id,author,classification,now,priority,25,topic,event_type,presenter_answer=answer)
            self.last_reason='PRESENTER_QUESTION_MATCH'
            self.metrics.update(self.counters)
            if answer['emoji']:return 'REACTION',item
            self.selected.append(item);self.counters['AUDIENCE_MESSAGES_SELECTED']+=1
            self.metrics.update(self.counters)
            return 'SELECT',item
        if classification == "SPAM" or (classification=="REACTION" and not local_safe_bypass) or (classification=="GREETING" and mode in {"BUSY","VERY_BUSY"} and not local_safe_bypass):
            self.last_reason=('SPAM_FILTER' if classification=='SPAM' else
                              'REACTION_ONLY' if classification=='REACTION' else 'GREETING_SUPPRESSED_BUSY')
            self.counters["AUDIENCE_SPAM_IGNORED" if classification=="SPAM" else "AUDIENCE_MESSAGES_SILENCED"]+=1; return "SILENCE", None
        if classification == "QUESTION" and not local_safe_bypass and event_type == "CHAT" and priority < 3:
            group, joined = self.trends.observe(author, text)
            self.counters["AUDIENCE_GROUPED_QUESTIONS"] = self.trends.counts["TREND_MESSAGES_AGGREGATED"]
            self.counters["AUDIENCE_TRENDING_QUESTIONS"] = self.trends.counts["TREND_CLUSTERS_TRENDING"]
            self.metrics.update(self.trends.snapshot())
            self.metrics["TREND_LAST_CLUSTER"] = group
            if joined:
                self.last_reason = "TREND_CLUSTER_AGGREGATED"
                self.counters["AUDIENCE_MESSAGES_SILENCED"] += 1
                self.metrics.update(self.counters)
                return "SILENCE", None
        score=priority*10 + (8 if classification=="QUESTION" else 5 if classification=="FOLLOWUP" else 0) + (3 if "jarvis" in text.casefold() else 0)
        if mode=="VERY_BUSY" and classification not in {"QUESTION","FOLLOWUP","CONTENT_REQUEST"} and priority<3 and not local_safe_bypass:
            self.last_reason='BUSY_NON_PRIORITY_COMMENT'
            self.counters["AUDIENCE_MESSAGES_SILENCED"]+=1; return "SILENCE",None
        if priority<3 and now-self.last_selected.get(author,-999)<self.config["fairness"] and not local_safe_bypass and classification!='CONTENT_REQUEST' and not (flow_decision and flow_decision.action=='CONTINUE_THREAD'):
            self.last_reason='AUTHOR_FAIRNESS_COOLDOWN'
            self.counters["AUDIENCE_MESSAGES_SILENCED"]+=1; return "WAIT",None
        item=AudienceItem(message_id,author,classification,now,priority,score,topic,event_type)
        self.selected.append(item); self.last_selected[author]=now; self.counters["AUDIENCE_MESSAGES_SELECTED"]+=1
        if self.session_memory: self.session_memory.selected(author)
        self.metrics.update(self.counters); self.metrics["AUDIENCE_PENDING_QUEUE"]=len(self.selected); self.metrics["AUDIENCE_UNIQUE_AUTHORS"]=len(self.authors)
        self.last_reason='SELECTED_FOR_PRESENTER'
        return "SELECT",item

    def mark_answered(self, item):
        self.counters["AUDIENCE_MESSAGES_ANSWERED"]+=1; self.answered.append((self.clock(),item.topic_key)); self.metrics.update(self.counters)
