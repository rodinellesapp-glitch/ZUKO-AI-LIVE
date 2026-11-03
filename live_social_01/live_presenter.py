"""Controlled, local presenter decisions built on audience/event snapshots."""
from __future__ import annotations
import re, time
from collections import deque
from dataclasses import dataclass
from live_engagement import LiveEngagementEngine
from live_reactions import reaction_details

OFF, ASSISTED, AUTO = "OFF", "ASSISTIDO", "AUTO"
CONFIG = {"cooldown":45, "budget":3, "budget_window":600, "suggestion_ttl":30}

@dataclass(frozen=True)
class PresenterSuggestion:
    kind: str; text: str; created_at: float; topic: str; source: str = "PRESENTER"
    cluster: dict | None = None
    engagement: object = None

class LivePresenterManager:
    def __init__(self, clock=time.monotonic, config=None, session_memory=None) -> None:
        self.session_memory = session_memory
        self.engagement = LiveEngagementEngine(clock=clock, session_memory=session_memory)
        self.clock, self.config, self.mode = clock, {**CONFIG, **(config or {})}, OFF
        self.state, self.last_reason, self.last_intervention = "SILÊNCIO", "OFF", 0.0
        self.history, self.budget, self.suggestion = deque(maxlen=3), deque(), None
        self.counters = {"PRESENTER_EVALUATIONS":0,"PRESENTER_INTERVENTIONS":0,"PRESENTER_RULE_INTERVENTIONS":0,
                         "PRESENTER_AI_INTERVENTIONS":0,"PRESENTER_SILENCES":0,"PRESENTER_STALE_DROPPED":0,
                         "PRESENTER_REPEAT_PREVENTED":0,"PRESENTER_ASSISTED_APPROVED":0,"PRESENTER_ASSISTED_DISCARDED":0,
                         "PRESENTER_AUTO_INTERVENTIONS":0}

    def _silence(self, reason):
        self.state, self.last_reason = "SILÊNCIO", reason; self.counters["PRESENTER_SILENCES"]+=1; return None

    def evaluate(self, audience: dict, tts: dict, *, high_pending=False, topic_shift=False, force=False):
        self.counters["PRESENTER_EVALUATIONS"]+=1; now=self.clock()
        if self.mode==OFF and not force: return self._silence("OFF")
        if high_pending: return self._silence("HIGH_EVENT_PENDING")
        if tts.get("TTS_STATE","IDLE") not in {"IDLE"}: return self._silence("TTS_BUSY")
        if audience.get("AUDIENCE_MODE")=="VERY_BUSY" and not force: return self._silence("CHAT_TOO_ACTIVE")
        if now-self.last_intervention<self.config["cooldown"] and not force: return self._silence("COOLDOWN")
        while self.budget and now-self.budget[0]>self.config["budget_window"]: self.budget.popleft()
        if len(self.budget)>=self.config["budget"] and not force: return self._silence("BUDGET_EXHAUSTED")
        topic=audience.get("AUDIENCE_TOPIC","geral")
        cluster = self.session_memory.trends.opportunity() if self.session_memory else audience.get("TREND_OPPORTUNITY")
        if cluster and (cluster["claimed"] or cluster["status"] != "TRENDING"):
            return self._silence("SESSION_REPEAT")
        previous_cluster = audience.get('TREND_LAST_CLUSTER')
        if not cluster and previous_cluster and previous_cluster['status'] in {'TRENDING', 'ADDRESSED', 'COOLDOWN'}:
            return self._silence('SESSION_REPEAT')
        if not cluster and self.session_memory and self.session_memory.presenter_repeated(topic):
            self.counters['PRESENTER_REPEAT_PREVENTED']+=1
            return self._silence('SESSION_REPEAT')
        if cluster:
            kind = "TRENDING_QUESTION"
            topic = cluster['entity'] or topic
            intro = "Tem bastante gente perguntando como eu fui desenvolvido." if cluster['intent'] == 'criacao' else "Tem bastante gente com essa dúvida."
            text = intro + (' ' + cluster['answer'] if cluster['answer'] else '')
        elif topic_shift and topic!="geral": kind,text="TRANSITION",f"A conversa foi para {topic} agora. Isso conecta bem com o que a gente já vinha explorando."
        elif topic!="geral" and audience.get("AUDIENCE_MESSAGES_RECEIVED",0)>=2: kind,text="TOPIC_COMMENT",f"Percebi bastante curiosidade sobre {topic}. Vamos por uma etapa de cada vez para ficar claro."
        elif force: kind,text="AUDIENCE_PROMPT","Mandem o que vocês querem entender sobre o projeto, que eu puxo o próximo ponto útil."
        else: return self._silence("NO_USEFUL_CONTEXT")
        normalized=re.sub(r"\W+"," ",text.casefold()).strip()
        if not cluster and normalized in self.history: self.counters["PRESENTER_REPEAT_PREVENTED"]+=1; return self._silence("REPEAT")
        self.last_reason = "READY"
        self.suggestion=PresenterSuggestion(kind,text,now,topic, "TRENDING" if cluster else "PRESENTER", cluster); self.state="SUGESTÃO" if self.mode==ASSISTED else "AVALIANDO"
        return self.suggestion

    def approve(self):
        if not self.suggestion: return None
        now=self.clock()
        if now-self.suggestion.created_at>self.config["suggestion_ttl"]:
            self.counters["PRESENTER_STALE_DROPPED"]+=1; self.suggestion=None; return self._silence("STALE_CONTEXT")
        item=self.suggestion
        if item.engagement and self.engagement.paused:
            self.suggestion=None
            return self._silence('HUMAN_PAUSE')
        if item.cluster:
            if item.cluster["claimed"]: return self._silence("SESSION_REPEAT")
            item.cluster["claimed"] = True
            item.cluster["claimed_at"] = now
        self.suggestion=None; self.last_intervention=now; self.history.append(re.sub(r"\W+"," ",item.text.casefold()).strip())
        if not item.engagement or (not item.engagement.sustain and not item.engagement.human_requested
                                  and item.engagement.category!='REACTION'): self.budget.append(now)
        if item.engagement: self.engagement.reserve(item.engagement)
        self.counters["PRESENTER_INTERVENTIONS"]+=1; self.counters["PRESENTER_AI_INTERVENTIONS" if item.cluster and not item.cluster["answer"] else "PRESENTER_RULE_INTERVENTIONS"]+=1; self.counters["PRESENTER_ASSISTED_APPROVED"]+=1
        self.state="FALANDO"; return item

    def discard(self):
        if self.suggestion: self.counters["PRESENTER_ASSISTED_DISCARDED"]+=1
        self.suggestion=None; return self._silence("DISCARDED")

    def observe_safe(self, ident, author, text, relevant=True):
        self.engagement.reactions.observe(ident, author, text)
        with self.engagement.lock:
            details=reaction_details(text)
            self.engagement.producer.audience(author,text,details)
            if details['emoji_count']:self.engagement.producer.state.recent_reactions.append((ident,tuple(details['categories'])))
        if relevant:
            self.engagement.activity()
            self.engagement.observe_topic(text)
            if self.suggestion and self.suggestion.engagement: self.suggestion=None

    def evaluate_live(self, audience, tts, director=None, force=False, next_topic=False):
        if self.mode==OFF or self.engagement.paused: return None
        if self.suggestion and self.clock()-self.suggestion.created_at<=self.config['suggestion_ttl']:
            return self.suggestion
        if self.session_memory and self.session_memory.trends.opportunity():
            return self.evaluate(audience,tts)
        self.engagement.sync_topic(audience.get('AUDIENCE_TOPIC','geral'))
        action=self.engagement.propose(tts,director,audience.get('AUDIENCE_CHAT_RATE',0),force,next_topic)
        if not action: return None
        if not action.sustain and not force and action.category!='REACTION':
            while self.budget and self.clock()-self.budget[0]>self.config['budget_window']: self.budget.popleft()
            if self.clock()-self.last_intervention<self.config['cooldown'] or len(self.budget)>=self.config['budget']:
                return self._silence('COOLDOWN_OR_BUDGET')
        self.suggestion=PresenterSuggestion(action.kind,action.text,self.clock(),action.topic,engagement=action)
        self.last_reason='READY'
        return self.suggestion

    def prepare_recap(self):
        return self.session_memory.recap() if self.session_memory else {'topics': [], 'events': {}}
