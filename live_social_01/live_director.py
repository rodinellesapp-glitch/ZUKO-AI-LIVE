"""Local orchestration of classified work. No model, platform or audio access."""
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
import threading
import time
import uuid


@dataclass(frozen=True)
class DirectorConfig:
    queue_limit: int = 24
    tts_pending_limit: int = 5
    history_limit: int = 2000
    priorities: dict = field(default_factory=lambda: {
        'LOCAL_VOICE': 90, 'HIGH_EVENT': 80, 'SUPER_CHAT_QUESTION': 75,
        'FOLLOWUP': 70, 'TRENDING': 65, 'QUESTION': 60, 'EVENT_RULE': 50,
        'LOCAL_TEXT': 60, 'CHAT': 40, 'PRESENTER': 10, 'SYSTEM': 0})
    ttls: dict = field(default_factory=lambda: {
        'LOCAL': 20, 'HIGH_EVENT': 90, 'QUESTION': 45, 'FOLLOWUP': 45,
        'CHAT': 45, 'AUDIENCE': 45, 'RULE': 30, 'PRESENTER': 8, 'SYSTEM': 8})


@dataclass
class DirectorUnit:
    unit_id: str
    source: str
    author_id: str
    event_type: str = 'CHAT'
    classification: str = 'CHAT'
    priority: int = 0
    created_at: float = field(default_factory=time.monotonic)
    ttl: float = 0
    conversation_version: int = 0
    requires_ai: bool = False
    requires_tts: bool = True
    content_ref: object = None
    status: str = 'RECEIVED'
    metadata: dict = field(default_factory=dict)


class LiveDirectorManager:
    def __init__(self, dispatch, tts_snapshot=lambda: {}, clock=time.monotonic, config=None):
        self.dispatch, self.tts_snapshot, self.clock = dispatch, tts_snapshot, clock
        self.config = config or DirectorConfig()
        self.lock = threading.RLock()
        self.audience_units = OrderedDict()
        self.overlay_session = uuid.uuid4().hex
        self.overlay_version = 0
        self.overlay_last = None
        self.generation_ready_at = lambda: 0
        self.pending_units = []
        self.active_unit = None
        self.prefer_recent = False
        self.state = 'IDLE'
        self.paused = False
        self.closed = False
        self.epoch = 0
        self.activity_version = 0
        self.versions = OrderedDict()
        self.seen = OrderedDict()
        self.input_seen = OrderedDict()
        self.playback_guards = OrderedDict()
        self.logs = deque(maxlen=300)
        self.history = deque(maxlen=self.config.history_limit)
        self.counts = Counter({key: 0 for key in (
            'DIRECTOR_UNITS_RECEIVED','DIRECTOR_UNITS_DISPATCHED','DIRECTOR_UNITS_QUEUED',
            'DIRECTOR_UNITS_PROMOTED','DIRECTOR_UNITS_DROPPED','DIRECTOR_UNITS_STALE',
            'DIRECTOR_DUPLICATES','DIRECTOR_HIGH_EVENTS','DIRECTOR_PRESENTER_DROPPED')})
        self.wait_total = 0.0
        self.wake = threading.Event()
        self.worker = None

    def _log(self, name, unit=None, **details):
        # No message text, names, prompt or content_ref in diagnostics.
        correlation = unit.metadata.get('correlation_id','') if unit else ''
        correlations = unit.metadata.get('correlation_ids',()) if unit else ()
        fields = [('source', unit.source), ('type', unit.event_type)] if unit else []
        if correlation: fields.append(('correlation_id', correlation))
        if correlations: fields.append(('input_correlations', len(correlations)))
        if unit:
            for key in ('zuko_dispatch_outcome', 'zuko_outcome_reason', 'zuko_provider', 'zuko_model'):
                value = unit.metadata.get(key)
                if value not in (None, ''):
                    fields.append((key.removeprefix('zuko_'), value))
            fields.append(('unit_status', unit.status))
        fields.extend((key, value) for key, value in details.items() if value not in (None, ''))
        self.logs.append(name + ''.join(f' | {key}={value}' for key, value in fields))

    def _bound(self, mapping):
        while len(mapping) > self.config.history_limit: mapping.popitem(last=False)

    def reserve_input(self, ident):
        with self.lock:
            if ident in self.input_seen:
                self.counts['DIRECTOR_DUPLICATES'] += 1
                self._log('DIRECTOR_DUPLICATE_DROPPED')
                return False
            self.input_seen[ident] = None; self._bound(self.input_seen)
            return True

    def conversation_arrived(self, author):
        with self.lock:
            version = self.versions.get(author, 0) + 1
            self.versions[author] = version
            self.versions.move_to_end(author); self._bound(self.versions)
            self._activity()
            self._prune()
            return version

    def _activity(self):
        self.activity_version += 1
        for unit in list(self.pending_units):
            if unit.source == 'PRESENTER': self._finish_pending(unit, 'STALE')

    def _finish_pending(self, unit, status):
        if unit in self.pending_units: self.pending_units.remove(unit)
        unit.status = status
        if status == 'STALE':
            self.counts['DIRECTOR_UNITS_STALE'] += 1; self._log('DIRECTOR_STALE_DROPPED', unit)
            self._log('DIRECTOR_STALE', unit)
        else:
            self.counts['DIRECTOR_UNITS_DROPPED'] += 1; self._log('DIRECTOR_DROP', unit)
        if unit.source == 'PRESENTER': self.counts['DIRECTOR_PRESENTER_DROPPED'] += 1
        self.history.append((unit.unit_id, status))
        unit.content_ref = None

    def _preparation_credit(self,unit):
        started=unit.metadata.get('provider_preparation_started')
        if started is None:return 0
        snapshot=getattr(self,'preparation_snapshot',lambda:{})()
        return min(45,max(0,min(self.clock(),snapshot.get('finished') or self.clock())-started))

    def _stale(self, unit):
        reason=''
        if unit.metadata.get('presenter_cancelled'):reason='PRESENTER_CANCELLED'
        elif self.clock() - unit.created_at - self._preparation_credit(unit) >= unit.ttl:reason='TTL_EXPIRED'
        elif unit.metadata['epoch'] != self.epoch:reason='SESSION_EPOCH_CHANGED'
        elif unit.source == 'PRESENTER' and unit.metadata['activity'] != self.activity_version:
            reason='SUPERSEDED_BY_AUDIENCE_ACTIVITY'
        elif (unit.source in {'LOCAL','AUDIENCE'} and unit.conversation_version and
              unit.conversation_version < self.versions.get(unit.author_id, 0)):
            reason='SUPERSEDED_BY_NEWER_AUTHOR_COMMENT'
        if reason:unit.metadata['director_stale_reason']=reason
        return bool(reason)

    def _prune(self):
        for unit in list(self.pending_units):
            if self._stale(unit): self._finish_pending(unit, 'STALE')

    def _priority(self, unit):
        p = self.config.priorities
        if unit.classification == 'CRITICAL': return 100
        if unit.source == 'HUMAN_COMMAND': return 78
        if unit.metadata.get('input_source') == 'LOCAL_VOICE': return p['LOCAL_VOICE']
        if unit.source == 'HIGH_EVENT': return p['SUPER_CHAT_QUESTION' if unit.requires_ai and unit.event_type == 'SUPER_CHAT' else 'HIGH_EVENT']
        if unit.source == 'PRESENTER': return 30 if unit.classification == 'ENGAGEMENT' else p['PRESENTER']
        if unit.source == 'SYSTEM': return p['SYSTEM']
        if unit.event_type != 'CHAT': return p['EVENT_RULE']
        if unit.classification=='PRESENTER_ANSWER':return 62
        if unit.classification in {'FOLLOWUP','QUESTION','TRENDING'}: return p[unit.classification]
        if unit.source == 'LOCAL': return p['LOCAL_TEXT']
        return p.get(unit.classification, p['CHAT'])

    def submit(self, unit):
        with self.lock:
            self.counts['DIRECTOR_UNITS_RECEIVED'] += 1; self._log('DIRECTOR_RECEIVED', unit)
            if self.closed or self.paused:
                self._finish_pending(unit,'DROPPED'); return False
            if unit.unit_id in self.seen:
                self.counts['DIRECTOR_DUPLICATES'] += 1
                self._log('DIRECTOR_DUPLICATE_DROPPED', unit); unit.status='DROPPED'; unit.content_ref=None
                return False
            self.seen[unit.unit_id]=None; self._bound(self.seen)
            if getattr(self,'preparation_snapshot',lambda:{})().get('state')=='INICIALIZANDO':
                unit.metadata['provider_preparation_started']=self.clock()
            unit.metadata.setdefault('epoch',self.epoch)
            unit.metadata.setdefault('activity',self.activity_version)
            unit.priority=self._priority(unit)
            if not unit.ttl:
                key = unit.source if unit.source in {'HIGH_EVENT','LOCAL','PRESENTER'} else unit.classification
                unit.ttl=self.config.ttls.get(key,self.config.ttls.get(unit.source,15))
            if unit.metadata.get('moderation_hold'):
                self._finish_pending(unit,'SILENCED'); return False
            if unit.metadata.get('audience_mode') == 'VERY_BUSY' and unit.priority < self.config.priorities['EVENT_RULE']:
                self._finish_pending(unit,'SILENCED'); return False
            if unit.source != 'PRESENTER': self._activity()
            if unit.source == 'HIGH_EVENT': self.counts['DIRECTOR_HIGH_EVENTS'] += 1
            self._prune()
            if unit.source=='PRESENTER' and (
                    any(other.source!='PRESENTER' for other in self.pending_units) or
                    (self.active_unit is not None and self.active_unit.source!='PRESENTER') or
                    any(other.status not in {'STALE','DROPPED','ERROR','SILENCED'} for other in self.audience_units.values())):
                unit.metadata['zuko_outcome_reason']='AUDIENCE_PRIORITY_WAIT'
                self._finish_pending(unit,'SILENCED')
                return False
            if self._stale(unit): self._finish_pending(unit,'STALE'); return False
            promoted=any(other.priority < unit.priority for other in self.pending_units)
            unit.status='PROMOTED' if promoted else 'QUEUED'
            self.pending_units.append(unit)
            self.counts['DIRECTOR_UNITS_QUEUED'] += 1; self._log('DIRECTOR_QUEUE',unit)
            if promoted:
                self.counts['DIRECTOR_UNITS_PROMOTED'] += 1; self._log('DIRECTOR_PROMOTE',unit)
            if len(self.pending_units)>self.config.queue_limit:
                loser=min(self.pending_units,key=lambda item:(item.priority,item.metadata.get('social_value',0),item.created_at))
                self._finish_pending(loser,'DROPPED')
            if not self.active_unit: self.state='WAITING'
            resolver=getattr(self,'audience_name_resolver',None)
            if resolver and unit.status not in {'DROPPED','STALE','SILENCED'}:
                name=resolver(unit)
                if name is not None:self.register_audience(unit,name)
            self.wake.set()
            return unit.status not in {'DROPPED','STALE','SILENCED'}

    def run_once(self):
        # Device inspection and external dispatch callbacks run outside the director lock.
        try:
            tts=self.tts_snapshot()
            voice_ready=getattr(self,'voice_ready',lambda:True)()
        except Exception:
            with self.lock:
                self.state='ERROR'; self._log('DIRECTOR_TTS_STATUS_ERROR')
            return False
        with self.lock:
            if self.active_unit or self.paused or self.closed: return False
            self.state='ARBITRATING'; self._prune()
            if not self.pending_units: self.state='IDLE'; return False
            if getattr(self,'preparation_snapshot',lambda:{})().get('state')=='INICIALIZANDO':
                self.state='PREPARING';return False
            unit=min(self.pending_units,key=self._selection_key)
            if unit.requires_tts and not voice_ready:
                self.state='WAITING_VOICE'
                return False
            if tts.get('TTS_QUEUE_DEPTH', 0) >= self.config.tts_pending_limit:
                self.state='BLOCKED'; return False
            if unit.source == 'PRESENTER' and (tts.get('TTS_STATE','IDLE')!='IDLE' or tts.get('TTS_QUEUE_DEPTH',0)):
                self.state='BLOCKED'; return False
            if not getattr(unit.metadata.get('flow_decision'),'source_kind','')=='VIEWER_JOIN' and self.clock() < self.generation_ready_at():
                self.state='WAITING_GEMINI_SLOT'
                return False
            unit.created_at += self._preparation_credit(unit)
            unit.metadata.pop('provider_preparation_started',None)
            self.pending_units.remove(unit); self.active_unit=unit
            unit.status='DISPATCHED'; self.state='DISPATCHING'
            self.audience_state(unit.unit_id,'gerando')
            self.wait_total += max(0,self.clock()-unit.created_at)*1000
            self.counts['DIRECTOR_UNITS_DISPATCHED'] += 1; self._log('DIRECTOR_DISPATCH',unit)
        try:
            self.dispatch(unit)  # Must wait for generation completion, never for playback.
        except Exception:
            with self.lock: unit.status='ERROR'; self.state='ERROR'; self._log('DIRECTOR_ERROR',unit)
        finally:
            with self.lock:
                if unit.status not in {'ERROR','STALE','DROPPED','SILENCED'}: unit.status='COMPLETED'
                if unit.unit_id in self.audience_units:
                    state='aguardando áudio' if unit.metadata.get('zuko_dispatch_outcome')=='RESPONSE_QUEUED' else 'expirado' if unit.status=='STALE' else 'falhou'
                    if unit.metadata.get('audience_state') not in {'respondendo','sintetizada'}:self.audience_state(unit.unit_id,state)
                self.history.append((unit.unit_id,unit.status)); unit.content_ref=None
                self.active_unit=None
                if self.state!='ERROR': self.state='WAITING' if self.pending_units else 'IDLE'
                self._log('DIRECTOR_COMPLETE', unit,
                          outcome=unit.metadata.get('zuko_dispatch_outcome', 'DISPATCH_RETURNED_NO_OUTCOME'),
                          outcome_reason=unit.metadata.get('zuko_outcome_reason', ''))
        return True

    def before_tts(self, ident):
        with self.lock:
            unit=self.active_unit
            if unit is None or unit.unit_id!=ident: return True
            if self._stale(unit):
                if unit.status!='STALE': self._finish_pending(unit,'STALE')
                return False
            unit.status='ANSWERED'; self.history.append((ident,'ANSWERED'))
            return True

    def before_generation(self, ident):
        """A client lock may have delayed dispatch; revalidate before the API call."""
        with self.lock:
            unit = self.active_unit
            if unit is not None and unit.unit_id == ident and self._stale(unit):
                if unit.status != 'STALE': self._finish_pending(unit, 'STALE')
                return False
            return True

    def tts_queued(self, ident):
        with self.lock:
            if self.active_unit and self.active_unit.unit_id==ident:
                self.active_unit.status='TTS_QUEUED'; self.history.append((ident,'TTS_QUEUED'))
                self.playback_guards[ident] = self.active_unit
                self._bound(self.playback_guards)

    def allow_playback(self, ident):
        """Recheck pending speech only; never interrupt synthesis/playback in progress."""
        with self.lock:
            unit = self.playback_guards.pop(ident, None)
            if unit is not None and self._stale(unit):
                self._finish_pending(unit, 'STALE')
                return False
            return True

    def set_paused(self, paused):
        with self.lock: self.paused=paused
        self.wake.set()

    def invalidate(self):
        with self.lock:
            self.epoch += 1; self._prune()
        self.wake.set()

    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive(): return
            self.worker=threading.Thread(target=self._run,name='live-director',daemon=True); self.worker.start()

    def _run(self):
        while not self.closed:
            if not self.run_once(): self.wake.wait(.1); self.wake.clear()

    def close(self):
        self.invalidate(); self.closed=True; self.wake.set()
        with self.lock:
            for ident in list(self.audience_units):self.audience_state(ident,'falhou')

    def snapshot(self):
        with self.lock:
            self._prune()
            upcoming=min(self.pending_units,key=self._selection_key,default=None)
            return {**self.counts,'DIRECTOR_STATE':self.state,
                'DIRECTOR_QUEUE_DEPTH':len(self.pending_units),
                'DIRECTOR_ACTIVE':f'{self.active_unit.source} / {self.active_unit.event_type}' if self.active_unit else 'â€”',
                'DIRECTOR_NEXT':f'{upcoming.source} / {upcoming.priority}' if upcoming else 'â€”',
                'DIRECTOR_AVG_WAIT_MS':self.wait_total/max(1,self.counts['DIRECTOR_UNITS_DISPATCHED'])}

    def drain_logs(self):
        with self.lock:
            result=list(self.logs); self.logs.clear(); return result

    def _selection_key(self,unit):
        # Preserve safety/event priorities and relevance; prefer fresh chat on ties.
        arrival=-unit.created_at if self.prefer_recent and unit.event_type=='CHAT' else unit.created_at
        return (-unit.priority,-unit.metadata.get('social_value',0),arrival)

    def cancel_presenter(self):
        with self.lock:
            self._activity()
            # Human-requested topic speech is still Presenter work. Pause cancels
            # pending speech, while audio whose guard was consumed keeps playing.
            units=list(self.pending_units)+list(self.playback_guards.values())
            if self.active_unit: units.append(self.active_unit)
            for unit in units:
                if unit.metadata.get('engagement_action'):
                    unit.metadata['presenter_cancelled']=True
            self._prune()

    def register_audience(self, unit, public_name):
        with self.lock:
            unit.metadata['public_name']=public_name or ''
            unit.metadata['audience_state']='aguardando'
            self.audience_units[unit.unit_id]=unit
            self._bound(self.audience_units)
            self._log('AUDIENCE_QUEUE_ACCEPTED',unit,name_available=bool(public_name))

    def audience_state(self, ident, state):
        with self.lock:
            unit=self.audience_units.get(ident)
            if unit:
                unit.metadata['audience_state']=state
                self._log('AUDIENCE_QUEUE_STATE',unit,state=state,wait_ms=round((self.clock()-unit.created_at)*1000))
                if state in {'concluído','expirado','falhou'}:self.audience_units.pop(ident,None)

    def audience_snapshot(self):
        with self.lock:
            self._prune()
            for ident,unit in list(self.audience_units.items()):
                if unit.status in {'STALE','DROPPED','ERROR','SILENCED'}:
                    self.audience_state(ident,'expirado' if unit.status=='STALE' else 'falhou')
            units=sorted(self.audience_units.values(),key=self._selection_key)
            current=next((u for u in units if u.metadata.get('audience_state')=='respondendo'),None)
            waiting=[u for u in units if u is not current]
            rows=[{'id':u.unit_id,'name':u.metadata.get('public_name',''), 'state':u.metadata.get('audience_state','aguardando')} for u in waiting[:4]]
            data={'rows':rows,'extra':max(0,len(waiting)-4),'current':({'id':current.unit_id,'name':current.metadata.get('public_name','')} if current else {})}
            if data!=self.overlay_last:self.overlay_version+=1;self.overlay_last=data
            return dict(data,session=self.overlay_session,version=self.overlay_version)
