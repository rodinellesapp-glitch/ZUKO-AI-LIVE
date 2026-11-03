"""Bounded public programme memory and aggregate, non-causal engagement signals."""
from collections import Counter, OrderedDict, deque
import hashlib
import re
import threading
import time
import unicodedata

from zuko_v3_content import FRAMES, TOPICS

KINDS={'CHAT':'COMMENT','CHAT_MESSAGE':'COMMENT','COMMENT':'COMMENT','GIFT':'GIFT',
       'GIFT_EVENT':'GIFT','FOLLOW':'FOLLOW','LIKE':'LIKE','LIKE_EVENT':'LIKE','REACTION':'LIKE',
       'SUPER_CHAT':'GIFT','MEMBER':'FOLLOW','SUBSCRIBE':'FOLLOW'}
TERMS={
    'trabalho_e_correria':('trabalho','trabalhei','servico','correria','chefe','segunda'),
    'supermercado_e_economia':('mercado','supermercado','compras','preco','economizar'),
    'familia_e_domingo':('familia','domingo','almoco','mae','pai'),
    'transporte_e_transito':('onibus','metro','transito','transporte','atraso'),
    'grupos_de_whatsapp':('whatsapp','grupo','mensagem','audio'),
    'vida_adulta':('adulto','adulta','boleto','conta','casa','rotina'),
    'costumes_e_geracoes':('costume','geracao','geracoes','jovem','antigamente'),
    'gambiarras_criativas':('gambiarra','gambiarras','conserto','improviso'),
    'inteligencia_artificial':('ia','inteligencia','modelo','algoritmo'),
    'manutencao_industrial':('manutencao','falha','maquina','vibracao'),
    'sensores_e_caldeiras':('sensor','sensores','caldeira','pressao','temperatura'),
    'robotica':('robo','robos','robotica'), 'energia':('energia','eletrica','solar'),
    'programacao':('codigo','python','programacao','programa'),
    'tecnologia_cotidiana':('celular','tecnologia','internet'),
    'seguranca_digital':('senha','seguranca','golpe','privacidade')}


def normalize(value):
    value=unicodedata.normalize('NFKD',str(value or '').casefold())
    return re.sub(r'[^a-z0-9 ]',' ',''.join(c for c in value if not unicodedata.combining(c)))


class AdaptiveMemory:
    def __init__(self, config, clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock()
        self.turn_limit=max(6,min(100,int(config.get('turns',24))))
        self.event_limit=max(20,min(2000,int(config.get('events',600))))
        self.ttl=max(60,min(7200,int(config.get('ttl_seconds',1800))))
        self.window=max(10,min(300,int(config.get('window_seconds',60))))
        self.turns=deque(maxlen=self.turn_limit)
        self.events=deque(maxlen=self.event_limit)
        self.seen=OrderedDict();self.totals=Counter();self.failures=Counter()
        self.frames={frame:Counter() for frame in FRAMES}
        self.topics=Counter()
        self.source_observed=False
        self.speech_state='IDLE';self.animation_state='UNKNOWN'

    def _prune(self):
        cutoff=self.clock()-self.ttl
        while self.turns and self.turns[0]['at']<cutoff:self.turns.popleft()
        while self.events and self.events[0]['at']<cutoff:self.events.popleft()
        while self.seen and next(iter(self.seen.values()))<cutoff:self.seen.popitem(last=False)

    def observe(self, kind, ident, *, text='', real=False, topic='', frame='', question_pending=False):
        kind=KINDS.get(str(kind).upper())
        if kind is None or not ident:return False
        # Identifiers exist only as expiring hashes in this in-memory dedup ledger.
        digest=hashlib.sha256((('REAL:' if real else 'SIM:')+kind+':'+str(ident)).encode('utf-8')).hexdigest()
        now=self.clock()
        with self.lock:
            self._prune()
            if digest in self.seen:self.totals['duplicates']+=1;return False
            self.seen[digest]=now
            while len(self.seen)>2*self.event_limit:self.seen.popitem(last=False)
            if not real:self.totals['simulated']+=1;return True
            self.source_observed=True
            words=set(normalize(str(text)[:500]).split())
            related=kind=='COMMENT' and bool(words.intersection(TERMS.get(topic,())))
            question=related and ('?' in str(text) or bool(words.intersection({'como','qual','porque','quando'})))
            challenge=related and bool(question_pending)
            valid_frame=frame if frame in FRAMES else ''
            self.events.append({'at':now,'kind':kind,'related':related,'question':question,
                                'challenge':challenge,'frame':valid_frame})
            self.totals[kind]+=1;self.totals['related_questions']+=int(question)
            self.totals['challenge_responses']+=int(challenge)
            if valid_frame:
                self.frames[valid_frame]['real_events']+=1
                self.frames[valid_frame]['related_questions']+=int(question)
                self.frames[valid_frame]['challenge_responses']+=int(challenge)
            return True

    def delivered(self, plan, speech, duration=None):
        with self.lock:
            self._prune()
            self.turns.append({'at':self.clock(),'frame':plan.frame,'topic':plan.topic,
                              'speech':str(speech)[:600],'intent':plan.intent})
            self.totals['completed']+=1;self.frames[plan.frame]['completed']+=1
            self.topics[plan.topic]+=1
            self.frames[plan.frame]['words']+=len(str(speech).split())
            if duration is not None:
                self.frames[plan.frame]['speech_seconds']+=max(0,min(120,float(duration)))
            self.speech_state='IDLE'

    def technical_failure(self, reason):
        allowed=('TTS_ERRO','TTS_CANCELLED','TTS_STALE_DROPPED','TTS_SKIPPED',
                 'PROVIDER_ERROR','REPEAT_GUARD','PENDING_EXPIRED','DIRECTOR_DISCARDED')
        category=reason if reason in allowed else 'OTHER'
        with self.lock:
            self.failures[category]+=1
            if category=='REPEAT_GUARD':self.totals['repetitions']+=1

    def context(self):
        with self.lock:
            self._prune()
            return {'public_programme_speech':[dict(row) for row in list(self.turns)[-4:]],
                    'engagement':self.engagement(),
                    'speech_state':self.speech_state,'animation_state':self.animation_state}

    def engagement(self):
        with self.lock:
            self._prune();now=self.clock()
            current=[row for row in self.events if now-row['at']<self.window]
            previous=[row for row in self.events if self.window<=now-row['at']<2*self.window]
            return {'data_status':'OBSERVED' if current else 'UNKNOWN',
                    'current_events':len(current),'previous_events':len(previous),
                    'activity_delta':len(current)-len(previous) if current and previous else None,
                    'related_questions':sum(row['question'] for row in current),
                    'challenge_responses':sum(row['challenge'] for row in current),
                    'association_only':True,'window_seconds':self.window}

    def summary(self):
        with self.lock:
            self._prune()
            return {'source_observed':self.source_observed,
                    'frames':{name:dict(values) for name,values in self.frames.items() if values},
                    'topics':sorted(self.topics),
                    'totals':dict(self.totals),'technical_failures':dict(self.failures),
                    'association_only':True}

    def sizes(self):
        with self.lock:
            self._prune();return {'turns':len(self.turns),'events':len(self.events),'identities':len(self.seen)}
