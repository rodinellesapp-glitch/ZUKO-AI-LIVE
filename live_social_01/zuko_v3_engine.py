"""Bounded programme scheduling; all generation and playback stay with V2 owners."""
from collections import Counter, OrderedDict, deque
from dataclasses import replace
import threading
import time
import uuid

from zuko_v3_content import ContentPlanner, load_config
from zuko_v3_memory import AdaptiveMemory
from zuko_v3_learning import EvidenceStore, ReflectionWorker


class AutonomousEngine:
    PHASES={'IDLE','OPENING','PRESENTING','LISTENING','RESPONDING','REACTING','TRANSITIONING','PAUSED'}
    LEGACY_PHASES={'PAUSADO':'PAUSED','ABERTURA':'OPENING','APRESENTANDO':'PRESENTING',
        'AGUARDANDO_RESPOSTA':'LISTENING','INTERAGINDO':'RESPONDING','DESAFIANDO':'PRESENTING',
        'IMPROVISANDO':'TRANSITIONING','REFLETINDO':'IDLE','ENCERRANDO':'IDLE'}
    PHASE_LABELS={'IDLE':'AGUARDANDO','OPENING':'ABERTURA','PRESENTING':'APRESENTANDO',
        'LISTENING':'AGUARDANDO_RESPOSTA','RESPONDING':'INTERAGINDO','REACTING':'REAGINDO',
        'TRANSITIONING':'RETOMANDO','PAUSED':'PAUSADO'}

    @property
    def state(self):
        return self._legacy_state

    @state.setter
    def state(self,value):
        # Keep V3 labels compatible; there is only one decision controller.
        self._legacy_state=value
        self.controller_state=self.LEGACY_PHASES.get(value,'IDLE')

    def _transition(self,phase,reason=None):
        if phase not in self.PHASES:raise ValueError('V4_PHASE_INVALID')
        self.controller_state=phase
        self._legacy_state=self.PHASE_LABELS[phase]
        if reason is not None:self.last_reason=reason

    def __init__(self, config=None, clock=time.monotonic, store_path=None):
        self.config=config or load_config()
        self.clock=clock
        self.lock=threading.RLock()
        self.enabled=False
        self.paused=False
        self.closed=False
        self.mode=self.config['default_mode']
        self.state='PAUSADO'
        self.session_id=''
        self.planner=ContentPlanner()
        self.memory=AdaptiveMemory(self.config['memory'],clock)
        self.store=EvidenceStore(store_path,self.config['learning'])
        self.reflection=ReflectionWorker()
        self.reflection_gemini=self.config['reflection'].get('use_gemini',False)
        self.last_reflection_count=0
        self.suggestion=None
        self.last_suggestion=None
        self.extra_pause=0
        self.pending=OrderedDict()
        self.counts=Counter()
        self.calls_minute=deque()
        self.last_finished=clock()
        self.backoff_until=0.0
        self.circuit_until=0.0
        self.consecutive_errors=0
        self.sequence=0
        self.last_reason='Desligado pelo operador'
        self.estimated_input_tokens=0
        self.estimated_output_tokens=0
        self.interrupted=False
        self.audience_pending=OrderedDict()
        self.interval_seconds=None
        self._transition('IDLE')

    def configure_planning(self,topic,interval_seconds):
        if type(interval_seconds) is not int or not 10<=interval_seconds<=300:
            raise ValueError('V4_INTERVAL_INVALID')
        with self.lock:
            self.planner.suggest_topic(topic)
            self.interval_seconds=interval_seconds
            return {'accepted':True,'operator_topic':self.planner.operator_topic,
                    'interval_seconds':self.interval_seconds}

    def track_audience(self,ident,kind='CHAT_MESSAGE'):
        """Track only selected Director units; no names or messages are stored."""
        if not ident:return False
        with self.lock:
            if self.closed or self.paused or ident in self.audience_pending:return False
            self.audience_pending[ident]={'at':self.clock(),'kind':str(kind).upper(),'stage':'WAITING'}
            while len(self.audience_pending)>64:self.audience_pending.popitem(last=False)
            self.reflection.cancel()
            phase='RESPONDING' if str(kind).upper() in {'CHAT','CHAT_MESSAGE','COMMENT'} else 'REACTING'
            if self.memory.speech_state!='PLAYING':
                self._transition(phase,'Interação selecionada tem prioridade sobre a apresentação')
            return True

    def audience_failed(self,ident):
        with self.lock:
            item=self.audience_pending.pop(ident,None)
            if item is not None:
                self.counts['audience_failures']+=1
                self.last_finished=self.clock()
                if item['stage']=='PLAYING':self.memory.speech_state='IDLE'
            if not self.audience_pending and self.enabled and not self.paused:
                self._transition('LISTENING')

    def repeated_question(self,speech):
        with self.lock:return self.planner.repeated_question(speech)

    def enable(self, enabled):
        with self.lock:
            enabled=bool(enabled)
            if enabled and self.closed:return False
            if enabled and not self.enabled:
                self.reflection.cancel()
                self.session_id=uuid.uuid4().hex
                operator_topic=self.planner.operator_topic
                self.planner=ContentPlanner();self.planner.suggest_topic(operator_topic)
                self.pending.clear();self.counts.clear()
                self.memory=AdaptiveMemory(self.config['memory'],self.clock)
                self.calls_minute.clear();self.sequence=0;self.consecutive_errors=0
                self.circuit_until=0;self.backoff_until=0;self.interrupted=False
                self.estimated_input_tokens=self.estimated_output_tokens=0
                self.last_reflection_count=0;self.suggestion=None;self.last_suggestion=None;self.extra_pause=0
                self.last_finished=self.clock()-(self.interval_seconds or self.config['modes'][self.mode]['interval'])
                self.state='ABERTURA';self.last_reason='Aguardando Director, voz e Godot'
            elif not enabled:
                if self.enabled and self.session_id:
                    self.store.add_session(self.session_id,self.memory.summary())
                self.reflection.cancel()
                self.pending.clear();self.state='ENCERRANDO';self.last_reason='Encerrado pelo operador'
            self.enabled=enabled
            return True

    def set_mode(self, mode):
        if mode not in self.config['modes']:raise ValueError('V3_MODE_INVALID')
        with self.lock:self.mode=mode;self.interval_seconds=None

    def pause(self, paused):
        with self.lock:
            self.paused=bool(paused)
            if paused:self.pending.clear();self.audience_pending.clear();self.state='PAUSADO';self.reflection.cancel()
            elif self.enabled:self.state='APRESENTANDO';self.last_finished=self.clock()

    def observe_input(self):
        with self.lock:
            if self.enabled:
                self.interrupted=True
                if self.memory.speech_state!='PLAYING':self.state='INTERAGINDO'
                self.reflection.cancel()

    def observe_signal(self,kind,ident,text='',real=False):
        with self.lock:
            if not self.enabled:return False
            accepted=self.memory.observe(kind,ident,text=text,real=real,
                frame=self.planner.frame,topic=self.planner.topic,
                question_pending=bool(self.planner.pending_question))
            if accepted and str(kind).upper() in {'CHAT','CHAT_MESSAGE','COMMENT','GIFT','GIFT_EVENT','FOLLOW','SUBSCRIBE','SUPER_CHAT'}:
                self.observe_input()
            return accepted

    def speech_started(self,ident):
        with self.lock:
            if ident in self.pending:
                self.pending[ident]['speech_at']=self.clock()
                plan=self.pending[ident]['plan']
                self._transition('OPENING' if plan.intent=='opening' else 'TRANSITIONING'
                    if plan.intent in {'resume','transition','answer_self'} else 'PRESENTING')
            elif ident in self.audience_pending:
                self.audience_pending[ident]['stage']='PLAYING'
                kind=self.audience_pending[ident]['kind']
                self._transition('RESPONDING' if kind in {'CHAT','CHAT_MESSAGE','COMMENT'} else 'REACTING')
            self.memory.speech_state='PLAYING'

    def request(self, *, tts_idle, director_busy, npc_ready, godot_speaking=False,
                session_active=True, weights=None, manual_active=False):
        now=self.clock()
        with self.lock:
            if self.paused:
                self._transition('PAUSED');return None
            if not self.enabled or self.closed or not session_active:
                self._transition('IDLE');return None
            for ident,item in list(self.pending.items()):
                if now-item['at']>self.config['limits']['pending_ttl_seconds']:
                    self.failed(ident,'PENDING_EXPIRED')
            if self.pending:return None
            if self.audience_pending:return None
            if manual_active:
                self._transition('IDLE','Aguardando conclusão do comando manual ativo');return None
            if not tts_idle or godot_speaking or director_busy or not npc_ready:
                if self.memory.speech_state!='PLAYING':self._transition('IDLE')
                self.last_reason='Aguardando prioridade do público, voz e Godot';return None
            if now<self.backoff_until:return None
            mode=self.config['modes'][self.mode]
            if self.planner.pending_question and not self.planner.topic_change_requested:
                if now<self.planner.pending_question['until']:
                    self.state='AGUARDANDO_RESPOSTA';return None
            elif now-self.last_finished<(self.interval_seconds or mode['interval'])+self.extra_pause:
                self._transition('LISTENING');return None
            suggestion=self.suggestion
            if suggestion and suggestion['action']=='change_topic' and not self.planner.pending_question:
                self.planner.step=3
            plan=self.planner.propose(mode,now,self.store.weights() if weights is None else weights)
            if plan is None:self.state='AGUARDANDO_RESPOSTA';return None
            if suggestion:
                action=suggestion['action']
                if action=='reduce_energy':plan=replace(plan,emotion='calm',gesture_intensity=0)
                elif action=='increase_energy' and mode['gesture_intensity']>0:plan=replace(plan,emotion='joy')
                elif action=='create_challenge' and not self.planner.pending_question and self.planner.completed>=2:
                    plan=replace(plan,intent='challenge',state='DESAFIANDO',next_action='wait_for_response',
                        objective='Crie um desafio novo ligado ao tema, sem repetir a pergunta anterior.')
                elif action=='avoid_repeat':
                    plan=replace(plan,objective=plan.objective+' Use um ângulo diferente dos recentes.')
                self.suggestion=None
            self.reflection.cancel()
            self.sequence+=1
            ident='zuko-v3:'+self.session_id[:12]+':'+str(self.sequence)
            self.pending[ident]={'plan':plan,'at':now,'queued':False}
            self.state=plan.state;self.last_reason='Plano enviado ao Director'
            if plan.intent in {'resume','transition','answer_self'}:self._transition('TRANSITIONING')
            return ident,plan

    def maybe_reflect(self, *, idle, model=None):
        with self.lock:
            policy=self.config['reflection']
            if (not self.enabled or self.paused or not idle or self.pending or self.audience_pending or
                self.counts['reflections']>=policy['max_per_session'] or
                self.counts['completed']-self.last_reflection_count<policy['every_completed']):return False
            context={'topic':self.planner.topic,'frame':self.planner.frame,
                'engagement':self.memory.engagement(),'summary':self.memory.summary()}
            if self.reflection.start(context,model if self.reflection_gemini else None):
                self.last_reflection_count=self.counts['completed'];self.counts['reflections']+=1
                self.state='REFLETINDO';return True
            return False

    def poll_reflection(self):
        suggestion=self.reflection.poll()
        with self.lock:
            if suggestion and self.enabled and not self.paused:
                self.suggestion=suggestion;self.last_suggestion=suggestion
                self.extra_pause=5 if suggestion['action']=='reduce_energy' else 0
                self.state='APRESENTANDO'
            return suggestion

    def reconcile(self, active_ids):
        with self.lock:
            for ident,item in list(self.pending.items()):
                if ident not in active_ids and self.clock()-item['at']>1:
                    self.failed(ident,'DIRECTOR_DISCARDED')
            for ident,item in list(self.audience_pending.items()):
                if (ident not in active_ids and self.clock()-item['at']>1) or self.clock()-item['at']>120:
                    self.audience_failed(ident)

    def queued(self, ident, metadata=None):
        with self.lock:
            if ident in self.pending:
                self.pending[ident]['queued']=True
                self.pending[ident]['output']=dict(metadata or {})

    def completed(self, ident, speech, metadata=None):
        now=self.clock()
        with self.lock:
            item=self.pending.pop(ident,None)
            if not item:return False
            plan=item['plan']
            metadata=metadata or item.get('output',{})
            # A model cannot close a session or change topic/control state itself.
            pause=metadata.get('suggested_pause_seconds',plan.pause_seconds)
            pause=max(2,min(30,float(pause)))
            self.planner.delivered(plan,speech,now,pause)
            duration=now-item['speech_at'] if 'speech_at' in item else None
            self.memory.delivered(plan,speech,duration)
            if self.interrupted:self.planner.resume=True
            self.interrupted=False
            self.last_finished=now;self.counts['completed']+=1
            self._transition('LISTENING')
            self.last_reason='Fala concluída com TTS_OK'
            return True

    def audience_delivered(self,ident=None):
        with self.lock:
            if ident is not None:self.audience_pending.pop(ident,None)
            self.memory.speech_state='IDLE'
            if not self.enabled:
                self._transition('PAUSED' if self.paused else 'IDLE');return
            self.last_finished=self.clock();self.planner.audience_reply_delivered()
            with self.memory.lock:self.memory.totals['audience_completed']+=1
            self.interrupted=False;self.state='INTERAGINDO'
            if not self.audience_pending:self._transition('LISTENING')

    def failed(self, ident, reason):
        with self.lock:
            item=self.pending.pop(ident,None)
            if item is None:return
            if 'speech_at' in item:self.memory.speech_state='IDLE'
            self.memory.technical_failure(reason)
            self.counts['cancelled' if any(word in reason for word in ('STALE','CANCEL','DISCARD')) else 'failures']+=1
            self.last_reason=str(reason)[:100]
            self.backoff_until=self.clock()+self.config['limits']['failure_backoff_seconds']
            if self.enabled:self.state='APRESENTANDO'

    def allow_gemini(self, budget):
        now=self.clock();limits=self.config['limits']
        with self.lock:
            while self.calls_minute and now-self.calls_minute[0]>=60:self.calls_minute.popleft()
            if self.paused or self.closed:return False,'PAUSED'
            if not budget.get('authorized'):return False,'AUTH_REQUIRED'
            if now<self.circuit_until:return False,'CIRCUIT_OPEN'
            remaining=budget.get('remaining')
            if remaining is not None and remaining<=limits['audience_reserve_calls']:
                return False,'AUDIENCE_RESERVE'
            if self.counts['gemini_calls']>=limits['autonomous_gemini_per_session']:
                return False,'AUTONOMOUS_SESSION_LIMIT'
            if len(self.calls_minute)>=limits['autonomous_gemini_per_minute']:
                return False,'AUTONOMOUS_RATE_LIMIT'
            return True,'READY'

    def gemini_started(self, input_chars=0, output_cap=256):
        with self.lock:
            self.calls_minute.append(self.clock());self.counts['gemini_calls']+=1
            self.estimated_input_tokens+=(max(0,int(input_chars))+3)//4
            self.estimated_output_tokens+=max(0,int(output_cap))

    def provider_result(self, success):
        with self.lock:
            if success:self.consecutive_errors=0
            else:
                self.consecutive_errors+=1
                if self.consecutive_errors>=self.config['limits']['failure_threshold']:
                    self.circuit_until=self.clock()+self.config['limits']['circuit_seconds']

    def snapshot(self):
        with self.lock:
            active=next(iter(self.pending.values()),{}).get('plan')
            rates=self.config['cost']
            known=all(isinstance(rates.get(key),(int,float)) for key in ('input_per_million','output_per_million'))
            cost=((self.estimated_input_tokens*rates['input_per_million']+
                   self.estimated_output_tokens*rates['output_per_million'])/1_000_000 if known else None)
            totals=self.memory.summary()['totals']
            return {'enabled':self.enabled,'mode':self.mode,'state':self.state,
                'controller_state':self.controller_state,
                'interval_seconds':self.interval_seconds or self.config['modes'][self.mode]['interval'],
                'operator_topic':self.planner.operator_topic,
                'conversation_plan':(active.context() if active else {
                    'topic':self.planner.topic,'next_idea':'retomar' if self.planner.resume else 'desenvolver',
                    'subtopic':self.planner.resume_points[-1]['subtopic'] if self.planner.resume_points else '',
                    'planning_reason':'retomada do tema após comentário' if self.planner.resume else 'aguardando próximo planejamento',
                    'asked_questions':list(self.planner.questions),'story_anchors':list(self.planner.stories),
                    'resume_points':list(self.planner.resume_points)}),
                'audience_waiting':sum(row['stage']=='WAITING' and row['kind'] in {'CHAT','CHAT_MESSAGE','COMMENT'}
                    for row in self.audience_pending.values()),
                'audience_events_waiting':sum(row['stage']=='WAITING' and row['kind'] not in {'CHAT','CHAT_MESSAGE','COMMENT'}
                    for row in self.audience_pending.values()),
                'real_gifts':'OBSERVED' if totals.get('GIFT',0) else 'NOT_VERIFIED',
                'real_followers':'OBSERVED' if totals.get('FOLLOW',0) else 'NOT_VERIFIED',
                'frame':active.frame if active else self.planner.frame or 'Aguardando',
                'topic':active.topic if active else self.planner.topic or 'Aguardando',
                'next_action':('aguardar resposta' if self.planner.pending_question else 'retomar tema' if self.planner.resume else 'desenvolver programa'),
                'completed':self.counts['completed'],'failures':self.counts['failures'],
                'cancelled':self.counts['cancelled'],'gemini_calls':self.counts['gemini_calls'],
                'pending':len(self.pending),'reason':self.last_reason,
                'audience_reserve':self.config['limits']['audience_reserve_calls'],
                'autonomous_limit':self.config['limits']['autonomous_gemini_per_session'],
                'rpm':self.config['limits']['autonomous_gemini_per_minute'],
                'circuit_open':self.clock()<self.circuit_until,'cost_estimate':cost,
                'engagement':self.memory.engagement(),'memory_sizes':self.memory.sizes(),
                'learning':self.store.snapshot(),
                'reflection':{'used':self.counts['reflections'],'limit':self.config['reflection']['max_per_session'],
                    'gemini_enabled':self.reflection_gemini,'suggestion':self.last_suggestion,
                    'error':self.reflection.last_error,
                    'busy':bool(self.reflection.worker and self.reflection.worker.is_alive())},
                'currency':rates.get('currency','USD')}

    def close(self):
        self.enable(False)
        self.reflection.close()
        with self.lock:self.closed=True
