"""One process owner and one ordered animation transport. No audio or AI ownership."""
from pathlib import Path
import sys
import threading
import time
import queue
import json
import os
import uuid
from collections import OrderedDict
import msvcrt
from bridge_diagnostics import exception_details

RUNTIME = Path(__file__).resolve().parents[1] / 'npc_runtime'
sys.path.append(str(RUNTIME))
from npc_live_show import Runtime
from show_tcp import ShowClient
from npc_client import ANIMATIONS
from movement_automation import MovementSelector

AUTO_SETTINGS = RUNTIME / 'runtime' / 'automatic_movements.json'
LOCOMOTION = {'Walk', 'WalkWave', 'WalkYes', 'WalkNo', 'Walk_Gun', 'Run', 'Run_Gun', 'Run_Shoot'}
WALK_COMBO_GESTURES = ('Yes', 'No')
WALK_COMBO_SOURCE_ANIMATIONS = {'WalkWave':'Wave','WalkYes':'Yes','WalkNo':'No'}


class NPCPanelBridge:
    def __init__(self, root, button, close_button, port=18765, on_log=None):
        self.root, self.button, self.close_button = root, button, close_button
        self.port = port
        self.state, self.error = 'OFF', ''
        self.commands = queue.Queue(maxsize=64)
        self.manual_commands = queue.Queue(maxsize=16)
        self.lock = threading.RLock()
        self.seen = OrderedDict()
        self.speech = None
        self.tts_busy = False
        self.speech_correlation = None
        self.active_speech_correlation = None
        self.godot_speaking = False
        self.speech_animation = 'Idle'
        self.speech_emotion = 'calm'
        self.speech_intent = 'comment'
        self.speech_hints = OrderedDict()
        self.stopping = False
        self.runtime = self.client = self.lease = None
        self.records = []
        self.on_log = on_log
        self._movement_log_last = {}
        self._movement_log_suppressed = {}
        self.pending_movements = []
        self.active_movement = None
        self.last_status_key = None
        self.last_scenery_moving = None
        self.walk_context = None
        self.walking_requested = False
        self.presentation_preferences = {'speed': 1.0, 'live': False, 'resolution': '540x960'}
        self.presentation_status = {}
        self.pause_provider = lambda: False
        self.external_paused = False
        self.manual_override = False
        self.manual_override_before_pause = False
        self.external_override_before_pause = False
        self.manual_paused = False
        self.manual_current = None
        self.manual_state = 'Aguardando Godot'
        self.manual_awaiting_status = False
        self.manual_confirmed = False
        self.idle_walk_seconds, self.idle_rest_seconds = self._load_idle_cycle()
        self.auto_movements_enabled=self._load_auto_movements()
        self.walk_wave_enabled=self._load_walk_wave()
        self.walk_wave_pending=None
        self.walk_wave_last_error=''
        self.walk_wave_last_active=False
        self.walk_combo_enabled={gesture:self._load_walk_combo(gesture) for gesture in WALK_COMBO_GESTURES}
        self.walk_combo_pending={}
        self.walk_combo_last_active=''
        self.walk_combo_last_errors={}
        self.auto_selector=MovementSelector(walk_seconds=self.idle_walk_seconds,rest_seconds=self.idle_rest_seconds)
        self.auto_commands=[]
        self.auto_idle_walking=False
        self.trace_path = Path(__file__).resolve().parent / 'logs/npc_events.jsonl'
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        button.configure(command=self.open)
        close_button.configure(command=self.close_npc)
        self.worker = threading.Thread(target=self._run, daemon=True, name='npc-panel-owner')
        self.worker.start()
        self._poll()

    def record(self, name, **data):
        row = {'at':time.time(), 'name':name, **data}
        self.records.append(row)
        if len(self.records)>500: del self.records[:100]
        if self.trace_path.exists() and self.trace_path.stat().st_size>500000:
            self.trace_path.replace(self.trace_path.with_name(self.trace_path.stem+'.archive-'+str(time.time_ns())+'.jsonl'))
        with self.trace_path.open('a',encoding='utf-8') as f: f.write(json.dumps(row)+'\n')
        if (name.startswith('MOVEMENT_') or name.startswith('WALK_WAVE_') or name.startswith('WALK_COMBO_')) and self.on_log:
            try: self.on_log(name+' | '+json.dumps({k:v for k,v in row.items() if k!='name'},ensure_ascii=False,separators=(',',':')))
            except Exception: pass
        return row

    def _movement_record(self, name, origin, correlation_id=None, **data):
        if origin == 'LIKE' and name in {'MOVEMENT_TRIGGER','MOVEMENT_SKIPPED'}:
            key=(name,origin);now=time.monotonic();last=self._movement_log_last.get(key,0.0)
            if now-last<5.0:
                self._movement_log_suppressed[key]=self._movement_log_suppressed.get(key,0)+1
                return None
            suppressed=self._movement_log_suppressed.pop(key,0)
            self._movement_log_last[key]=now
            if suppressed:data['coalesced_events']=suppressed
        return self.record(name,origin=origin,correlation_id=correlation_id,**data)

    @staticmethod
    def _movement_origin(event_type):
        kind=str(event_type or '').upper()
        if kind in {'GIFT','GIFT_EVENT','SUPER_CHAT','DONATION'}:return 'GIFT'
        if kind in {'FOLLOW','SUBSCRIBE','MEMBERSHIP'}:return 'FOLLOW'
        if kind in {'LIKE','LIKE_EVENT','REACTION'}:return 'LIKE'
        if kind=='GEMINI_QUESTION':return 'SPEECH'
        if kind in {'CHAT_MESSAGE','COMMENT','VIEWER_JOIN'}:return 'CHAT'
        return 'IDLE'

    @staticmethod
    def _new_correlation_id():
        return uuid.uuid4().hex[:12]

    def _queue_movement_confirmation(self, correlation_id, origin, animation):
        if not animation:return
        with self.lock:
            cutoff=time.monotonic()-10.0
            self.pending_movements=[item for item in self.pending_movements if item['at']>=cutoff]
            self.pending_movements.append({'correlation_id':correlation_id,'origin':origin,'animation':animation,'at':time.monotonic()})
            if len(self.pending_movements)>32:self.pending_movements=self.pending_movements[-32:]

    def _observe_presentation_status(self, status):
        cutoff=time.monotonic()-10.0
        with self.lock:
            expired=[item for item in self.pending_movements if item['at']<cutoff]
            if expired:self.pending_movements=[item for item in self.pending_movements if item['at']>=cutoff]
        if expired:
            for item in expired:
                self._movement_record('MOVEMENT_SKIPPED',item['origin'],item['correlation_id'],reason='no_godot_confirmation',animation=item['animation'])
        previous=self.presentation_status
        old_moving=self.last_scenery_moving
        self.presentation_status=dict(status)
        self._sync_manual_priority(status,previous)
        animation=status.get('animation','')
        speaking=bool(status.get('speaking',False))
        previous_speaking=bool(previous.get('speaking',False))
        if speaking and animation=='Idle':
            with self.lock:
                speech_idle_index=next((i for i,item in enumerate(self.pending_movements)
                    if item['origin']=='SPEECH' and item['animation']=='Idle'),None)
                confirmed_speech_idle=(self.pending_movements.pop(speech_idle_index)
                                       if speech_idle_index is not None else None)
            if confirmed_speech_idle:
                self.active_speech_correlation=confirmed_speech_idle['correlation_id']
                self._movement_record('SPEECH_ANIMATION_CONFIRMED','SPEECH',
                    confirmed_speech_idle['correlation_id'],animation='Idle',
                    confirmed_by='Godot_speaking_status')
        if speaking:
            active_gesture=status.get('walk_combo_active','')
            with self.lock:
                speech_index=next((i for i,item in enumerate(self.pending_movements)
                    if item['origin']=='SPEECH' and
                    (item['animation']==animation or item['animation']==active_gesture or
                     (item['animation']=='Wave' and animation=='WalkWave'))),None)
                confirmed_speech=(self.pending_movements.pop(speech_index) if speech_index is not None else None)
            if confirmed_speech:
                self.active_speech_correlation=confirmed_speech['correlation_id']
                self._movement_record('SPEECH_ANIMATION_CONFIRMED','SPEECH',
                    confirmed_speech['correlation_id'],animation=animation,
                    gesture=active_gesture or confirmed_speech['animation'],confirmed_by='Godot_speaking_status')
        if 'walk_wave_enabled' in status:
            enabled=status.get('walk_wave_enabled')
            available=status.get('walk_wave_available',False)
            active=status.get('walk_wave_active',False)
            if self.walk_wave_pending is not None:
                if enabled==self.walk_wave_pending:
                    self.record('WALK_WAVE_MODE_CONFIRMED',enabled=enabled,available=available)
                    self.walk_wave_pending=None
                elif self.walk_wave_pending and not available:
                    self.record('WALK_WAVE_FAILURE',reason=status.get('walk_wave_error') or 'CANDIDATE_UNAVAILABLE',phase='enable')
                    self.walk_wave_enabled=False
                    self.walk_wave_pending=None
                    try:self._save_walk_wave(False)
                    except OSError:pass
            elif self.walk_wave_enabled and not enabled and not available:
                self.record('WALK_WAVE_FAILURE',reason=status.get('walk_wave_error') or 'CANDIDATE_UNAVAILABLE',phase='startup')
                self.walk_wave_enabled=False
                try:self._save_walk_wave(False)
                except OSError:pass
            current_error=status.get('walk_wave_error','')
            if current_error and current_error!=self.walk_wave_last_error:
                self.record('WALK_WAVE_FAILURE',reason=current_error,phase='build_or_runtime')
            self.walk_wave_last_error=current_error
            if active and not self.walk_wave_last_active:
                self.record('WALK_WAVE_START',animation=animation,walk_seconds=self.idle_walk_seconds)
            elif self.walk_wave_last_active and not active:
                self.record('WALK_WAVE_END',animation=animation,reason='cycle_or_priority_change')
            self.walk_wave_last_active=active
        combos=status.get('walk_combos',{})
        available=status.get('walk_combo_available',{})
        errors=status.get('walk_combo_errors',{})
        for gesture in WALK_COMBO_GESTURES:
            if gesture in self.walk_combo_pending and combos.get(gesture)==self.walk_combo_pending[gesture]:
                self.record('WALK_COMBO_MODE_CONFIRMED',gesture=gesture,enabled=combos[gesture],available=available.get(gesture,False))
                self.walk_combo_pending.pop(gesture,None)
            elif gesture in self.walk_combo_pending and self.walk_combo_pending[gesture] and not available.get(gesture,False):
                self.record('WALK_COMBO_FAILURE',gesture=gesture,reason=errors.get(gesture) or 'CANDIDATE_UNAVAILABLE',phase='enable')
                self.walk_combo_enabled[gesture]=False
                self.walk_combo_pending.pop(gesture,None)
                try:
                    data=self._auto_settings();data['walk_combo_'+gesture.lower()+'_enabled']=False
                    temp=AUTO_SETTINGS.with_suffix('.tmp');temp.write_text(json.dumps(data,separators=(',',':')),encoding='utf-8');os.replace(temp,AUTO_SETTINGS)
                except OSError:pass
            error=errors.get(gesture,'')
            if error and error!=self.walk_combo_last_errors.get(gesture,''):
                self.record('WALK_COMBO_FAILURE',gesture=gesture,reason=error,phase='build_or_runtime')
            self.walk_combo_last_errors[gesture]=error
        active_combo=status.get('walk_combo_active','')
        if active_combo!=self.walk_combo_last_active:
            if self.walk_combo_last_active:
                self.record('WALK_COMBO_END',gesture=self.walk_combo_last_active,animation=animation,
                            reason='cycle_or_priority_change',confirmed_by='Godot_status')
            if active_combo:
                self.record('WALK_COMBO_START',gesture=active_combo,animation=animation,
                            bones=status.get('walk_combo_bones',[]),tracks=status.get('walk_combo_tracks',[]),confirmed_by='Godot_status')
            self.walk_combo_last_active=active_combo
        reacting=bool(status.get('reacting',False))
        walking=bool(status.get('walking',False))
        paused=bool(status.get('paused',False))
        moving=walking and animation in LOCOMOTION and not paused
        state_key=(animation,reacting,walking)
        current_active=reacting or walking or (bool(status.get('manual',False)) and animation not in {'','Idle'})
        previous_active=self.active_movement is not None
        last_finished=None

        if old_moving is not None and moving!=old_moving:
            active=self.active_movement or {}
            with self.lock:
                pending_context=next((item for item in self.pending_movements if item['animation'] in {animation,WALK_COMBO_SOURCE_ANIMATIONS.get(animation)}),None)
            context=pending_context or active
            origin=context.get('origin') or ('MANUAL' if status.get('source')=='MANUAL' else 'IDLE')
            self._movement_record('MOVEMENT_SCENERY',origin,context.get('correlation_id'),enabled=moving,animation=animation,speed=status.get('speed'))
        self.last_scenery_moving=moving

        if previous_active and (not current_active or state_key!=self.last_status_key):
            finished=self.active_movement
            last_finished=finished
            self._movement_record('MOVEMENT_FINISHED',finished.get('origin','IDLE'),finished.get('correlation_id'),animation=finished.get('animation'),confirmed_by='Godot_status')
            self.active_movement=None

        if current_active and state_key!=self.last_status_key:
            with self.lock:
                pending_index=next((i for i,item in enumerate(self.pending_movements) if item['animation'] in {animation,WALK_COMBO_SOURCE_ANIMATIONS.get(animation)}),None)
                confirmed=self.pending_movements.pop(pending_index) if pending_index is not None else None
            source=status.get('source')
            if confirmed:
                movement=confirmed
            elif source=='MANUAL':
                movement={'origin':'MANUAL','correlation_id':None,'animation':animation}
            elif animation in LOCOMOTION and moving and self.walk_context:
                movement=dict(self.walk_context)
                movement['animation']=animation
            elif animation in LOCOMOTION and moving and source=='AUTOMÁTICO':
                movement={'origin':'IDLE','correlation_id':None,'animation':animation}
            else:
                movement=None
            if movement:
                movement['animation']=animation
                self.active_movement=movement
                if speaking and movement.get('origin')=='SPEECH':
                    self.active_speech_correlation=movement.get('correlation_id')
                    self._movement_record('SPEECH_ANIMATION_CONFIRMED','SPEECH',
                        movement.get('correlation_id'),animation=animation,
                        confirmed_by='Godot_status')
                if animation in LOCOMOTION and moving:self.walk_context=dict(movement)
                self._movement_record('MOVEMENT_STARTED',movement['origin'],movement.get('correlation_id'),animation=animation,confirmed_by='Godot_status')

        if animation=='Idle' and not reacting and not walking and (previous.get('animation') not in {'',None,'Idle'} or previous.get('walking',False)):
            with self.lock:
                pending_index=next((i for i,item in enumerate(self.pending_movements) if item['animation']=='Idle'),None)
                pending=self.pending_movements.pop(pending_index) if pending_index is not None else None
            context=self.active_movement or pending or self.walk_context or last_finished or {}
            origin=context.get('origin') or ('MANUAL' if status.get('source')=='MANUAL' else 'IDLE')
            self._movement_record('MOVEMENT_RETURN_IDLE',origin,context.get('correlation_id'),confirmed_by='Godot_status')
            self.walk_context=None
        elif not walking and animation not in LOCOMOTION:
            self.walk_context=None
        if previous_speaking and not speaking and animation=='Idle' and not reacting and not walking:
            if previous.get('animation') in {'',None,'Idle'}:
                correlation_id=self.active_speech_correlation or self.speech_correlation
                self._movement_record('MOVEMENT_RETURN_IDLE','SPEECH',correlation_id,
                                      confirmed_by='Godot_speaking_status')
            self.active_speech_correlation=None
        self.godot_speaking=speaking
        self.last_status_key=state_key

    def _sync_manual_priority(self,status,previous):
        """Release a completed manual gesture only on explicit Godot evidence."""
        with self.lock:
            if not self.manual_override:return
            requested=getattr(self,'manual_current',None)
            actual=status.get('animation')
            matches=actual==requested or WALK_COMBO_SOURCE_ANIMATIONS.get(actual)==requested
            if status.get('manual') is True and matches:
                self.manual_awaiting_status=False
                self.manual_confirmed=True
                return
            queued=getattr(self,'manual_commands',None)
            if (status.get('manual') is False and status.get('paused') is False
                and not self.manual_paused and not self.external_paused
                and not getattr(self,'manual_awaiting_status',False)
                and (getattr(self,'manual_confirmed',False) or previous.get('manual') is True)
                and (queued is None or queued.empty())):
                self.manual_override=False
                self.manual_confirmed=False
                self.manual_state='Animação manual concluída; AUTO liberado pelo Godot'
                self.record('MANUAL_PRIORITY_RELEASED',animation=actual,confirmed_by='Godot_status')
    @staticmethod
    def _load_auto_movements():
        try:
            value=json.loads(AUTO_SETTINGS.read_text(encoding='utf-8')).get('enabled',False)
            return value if type(value) is bool else False
        except (OSError,ValueError,AttributeError):
            return False

    @staticmethod
    def _load_walk_wave():
        try:
            value=json.loads(AUTO_SETTINGS.read_text(encoding='utf-8')).get('walk_wave_enabled',False)
            return value if type(value) is bool else False
        except (OSError,ValueError,AttributeError):
            return False

    @staticmethod
    def _load_walk_combo(gesture):
        try:
            value=json.loads(AUTO_SETTINGS.read_text(encoding='utf-8')).get('walk_combo_'+gesture.lower()+'_enabled',False)
            return value if type(value) is bool else False
        except (OSError,ValueError,AttributeError):
            return False

    @staticmethod
    def _auto_settings():
        try:
            data=json.loads(AUTO_SETTINGS.read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError,AttributeError):
            return {}

    @staticmethod
    def _load_idle_cycle():
        data=NPCPanelBridge._auto_settings()
        return MovementSelector._valid_cycle(data.get('walk_seconds',180),data.get('rest_seconds',30))

    @staticmethod
    def _save_auto_movements(enabled):
        AUTO_SETTINGS.parent.mkdir(parents=True,exist_ok=True)
        temp=AUTO_SETTINGS.with_suffix('.tmp')
        data=NPCPanelBridge._auto_settings();data['enabled']=enabled
        temp.write_text(json.dumps(data,separators=(',',':')),encoding='utf-8')
        os.replace(temp,AUTO_SETTINGS)

    @staticmethod
    def _save_walk_wave(enabled):
        AUTO_SETTINGS.parent.mkdir(parents=True,exist_ok=True)
        temp=AUTO_SETTINGS.with_suffix('.tmp')
        data=NPCPanelBridge._auto_settings();data['walk_wave_enabled']=enabled
        temp.write_text(json.dumps(data,separators=(',',':')),encoding='utf-8')
        os.replace(temp,AUTO_SETTINGS)

    def get_walk_wave(self):
        with self.lock:return self.walk_wave_enabled

    def set_walk_wave(self, enabled):
        if type(enabled) is not bool:return False
        with self.lock:
            previous=self.walk_wave_enabled
            if enabled and self.state=='ACTIVE' and self.presentation_status and not self.presentation_status.get('walk_wave_available',False):
                self.error='Walk + Wave indisponível; consulte a aba Diagnóstico.'
                self.record('WALK_WAVE_FAILURE',reason=self.presentation_status.get('walk_wave_error') or 'CANDIDATE_UNAVAILABLE',phase='panel_toggle')
                return False
            try:self._save_walk_wave(enabled)
            except OSError as error:
                self.error='Não foi possível salvar Walk + Wave: '+type(error).__name__
                return False
            if self.state=='ACTIVE':
                try:self.manual_commands.put_nowait(('walk_wave_mode',enabled,None,None))
                except queue.Full:
                    try:self._save_walk_wave(previous)
                    except OSError:pass
                    self.error='Fila de controle cheia; Walk + Wave não alterado.'
                    return False
                self.walk_wave_pending=enabled
            self.walk_wave_enabled=enabled
            self.record('WALK_WAVE_MODE_REQUESTED',enabled=enabled,automatic_movements=self.auto_movements_enabled)
        return True

    def set_walk_combo(self, gesture, enabled):
        if gesture not in WALK_COMBO_GESTURES or type(enabled) is not bool:return False
        with self.lock:
            previous=self.walk_combo_enabled[gesture]
            if enabled and self.state=='ACTIVE' and not self.presentation_status.get('walk_combo_available',{}).get(gesture,False):
                self.error='Walk + '+gesture+' indisponível; consulte a aba Diagnóstico.'
                self.record('WALK_COMBO_FAILURE',gesture=gesture,reason=self.presentation_status.get('walk_combo_errors',{}).get(gesture) or 'CANDIDATE_UNAVAILABLE',phase='panel_toggle')
                return False
            try:
                data=self._auto_settings();data['walk_combo_'+gesture.lower()+'_enabled']=enabled
                AUTO_SETTINGS.parent.mkdir(parents=True,exist_ok=True)
                temp=AUTO_SETTINGS.with_suffix('.tmp')
                temp.write_text(json.dumps(data,separators=(',',':')),encoding='utf-8')
                os.replace(temp,AUTO_SETTINGS)
            except OSError as error:
                self.error='Não foi possível salvar Walk + '+gesture+': '+type(error).__name__
                return False
            if self.state=='ACTIVE':
                try:self.manual_commands.put_nowait(('walk_combo_mode',(gesture,enabled),None,None))
                except queue.Full:
                    data=self._auto_settings();data['walk_combo_'+gesture.lower()+'_enabled']=previous
                    temp=AUTO_SETTINGS.with_suffix('.tmp');temp.write_text(json.dumps(data,separators=(',',':')),encoding='utf-8');os.replace(temp,AUTO_SETTINGS)
                    self.error='Fila de controle cheia; Walk + '+gesture+' não alterado.'
                    return False
                self.walk_combo_pending[gesture]=enabled
            self.walk_combo_enabled[gesture]=enabled
            self.record('WALK_COMBO_MODE_REQUESTED',gesture=gesture,enabled=enabled,automatic_movements=self.auto_movements_enabled)
        return True

    def get_idle_cycle(self):
        with self.lock:return self.idle_walk_seconds,self.idle_rest_seconds

    def set_idle_cycle(self, walk_seconds, rest_seconds):
        if type(walk_seconds) is not int or type(rest_seconds) is not int:return False
        if not 1<=walk_seconds<=3600 or not 1<=rest_seconds<=3600:return False
        with self.lock:
            data=self._auto_settings();data.update({'walk_seconds':walk_seconds,'rest_seconds':rest_seconds})
            AUTO_SETTINGS.parent.mkdir(parents=True,exist_ok=True)
            temp=AUTO_SETTINGS.with_suffix('.tmp')
            try:
                temp.write_text(json.dumps(data,separators=(',',':')),encoding='utf-8')
                os.replace(temp,AUTO_SETTINGS)
            except OSError as error:
                self.error='Não foi possível salvar o ciclo automático: '+type(error).__name__
                return False
            self.idle_walk_seconds,self.idle_rest_seconds=self.auto_selector.set_idle_cycle(walk_seconds,rest_seconds)
            self.record('IDLE_WALK_CYCLE_SAVED',walk_seconds=self.idle_walk_seconds,rest_seconds=self.idle_rest_seconds)
        return True

    def set_auto_movements(self, enabled):
        if type(enabled) is not bool:return False
        with self.lock:
            previous=self.auto_movements_enabled
            try:self._save_auto_movements(enabled)
            except OSError as error:
                self.error='Não foi possível salvar a preferência automática: '+type(error).__name__
                return False
            if self.state=='ACTIVE':
                try:self.manual_commands.put_nowait(('auto_mode',enabled,None,None))
                except queue.Full:
                    try:self._save_auto_movements(previous)
                    except OSError:pass
                    self.error='Fila de controle cheia; modo automático não alterado.'
                    return False
            self.auto_movements_enabled=enabled
            if not enabled:
                self.auto_commands.clear();self.auto_idle_walking=False
                self.auto_selector.set_idle_cycle(self.idle_walk_seconds,self.idle_rest_seconds)
            self.record('AUTO_MOVEMENTS_TOGGLED',enabled=enabled)
            self._movement_record('MOVEMENT_AUTO_ENABLED' if enabled else 'MOVEMENT_AUTO_DISABLED','MANUAL',None)
        return True

    def open(self):
        with self.lock:
            if self.state in {'STARTING','ACTIVE','CLOSING'}: return
            self.state, self.error = 'STARTING', ''
            self.commands.put_nowait(('open',time.monotonic(),None))

    def close_npc(self):
        with self.lock:
            if self.state not in {'ACTIVE','STARTING','ERROR'}: return
            self.state = 'CLOSING'

    def event(self, ident, command, text='', provider=''):
        if command not in {'comment','gift','follow'}: return
        kind={'comment':'CHAT_MESSAGE','gift':'GIFT','follow':'FOLLOW'}[command]
        return self.automatic_event(ident,kind,text,provider)

    def automatic_event(self, ident, event_type, text='', provider=''):
        origin=self._movement_origin(event_type)
        correlation_id=self._new_correlation_id()
        with self.lock:
            if self.state!='ACTIVE':return False
            self._movement_record('MOVEMENT_TRIGGER',origin,correlation_id,event_type=str(event_type or '').upper())
            if not self.auto_movements_enabled:
                self._movement_record('MOVEMENT_SKIPPED',origin,correlation_id,reason='automation_disabled')
                return False
            if self.manual_paused or self.external_paused:
                self._movement_record('MOVEMENT_SKIPPED',origin,correlation_id,reason='paused')
                return False
            if self.manual_override:
                self._movement_record('MOVEMENT_SKIPPED',origin,correlation_id,reason='manual_priority')
                return False
            key = ('auto',str(ident))
            if key in self.seen:
                self._movement_record('MOVEMENT_SKIPPED',origin,correlation_id,reason='repetition')
                return False
            self.seen[key] = None
            while len(self.seen)>2000: self.seen.popitem(last=False)
            idle_walking_before=self.auto_selector.idle_walking
            idle_changed_at_before=self.auto_selector.idle_changed_at
            walk_stop_pending_before=self.auto_selector.walk_stop_pending
            movement=self.auto_selector.choose(event_type,text,provider)
            if movement is None:
                if idle_walking_before:
                    self.auto_selector.idle_walking=True
                    self.auto_selector.idle_changed_at=idle_changed_at_before
                    self.auto_selector.walk_stop_pending=walk_stop_pending_before
                    self.auto_idle_walking=True
                self._movement_record('MOVEMENT_SKIPPED',origin,correlation_id,reason=self.auto_selector.last_skip_reason or 'no_matching_gesture')
                self.record('AUTO_MOVEMENT_SKIPPED',event_type=event_type,reason='cooldown_or_duplicate')
                return False
            combo_enabled=(self.walk_wave_enabled if movement.animation=='Wave' else self.walk_combo_enabled.get(movement.animation,False))
            keep_idle_walk=idle_walking_before and combo_enabled and movement.animation in {'Wave','Yes','No'}
            if keep_idle_walk:
                self.auto_selector.idle_walking=True
                self.auto_selector.idle_changed_at=idle_changed_at_before
                self.auto_selector.walk_stop_pending=walk_stop_pending_before
                self.auto_idle_walking=True
            if len(self.auto_commands)>=4:
                lowest=min(range(len(self.auto_commands)),key=lambda i:self.auto_commands[i][0])
                if self.auto_commands[lowest][0]>=movement.priority:
                    self._movement_record('MOVEMENT_SKIPPED',origin,correlation_id,reason='priority',animation=movement.animation)
                    self.record('AUTO_MOVEMENT_DROPPED',event_type=event_type,animation=movement.animation,reason='queue_full')
                    return False
                dropped=self.auto_commands.pop(lowest)
                self._movement_record('MOVEMENT_SKIPPED',dropped[5],dropped[3],reason='priority',animation=dropped[2])
            self.auto_commands.append((movement.priority,time.monotonic(),movement.animation,correlation_id,movement.cooldown,origin))
            self.auto_commands.sort(key=lambda item:(-item[0],item[1]))
            if not keep_idle_walk:self.auto_idle_walking=False
            self._movement_record('MOVEMENT_SELECTED',origin,correlation_id,animation=movement.animation,event_type=str(event_type or '').upper())
            self.record('AUTO_MOVEMENT_QUEUED',event_type=event_type,animation=movement.animation,
                        emotion=movement.emotion,intent=movement.intent,provider=provider or 'local')
        return True

    def set_speech_hint(self, ident, intent, emotion, intensity=1):
        intents={'opening':'greeting','explain':'comment','challenge':'question','question':'question',
                 'answer_self':'comment','transition':'comment','resume':'comment','humor':'comment','closing':'greeting',
                 'greeting':'greeting','gratitude':'comment','support':'support','affirmation':'affirmation',
                 'disagreement':'disagreement','celebration':'celebration','comment':'comment','story':'comment'}
        if intent not in intents or emotion not in {'calm','joy','surprise','gratitude','empathy'} or intensity not in (0,1,2):return False
        with self.lock:
            if not hasattr(self,'speech_hints'):self.speech_hints=OrderedDict()
            self.speech_hints[ident]={'intent':intents[intent],'emotion':emotion,'intensity':intensity}
            while len(self.speech_hints)>128:self.speech_hints.popitem(last=False)
        return True

    def tts(self, event, response, detail=''):
        ident = getattr(response,'comment_id',None)
        if event in {'TTS_INICIO','TTS_OK','TTS_ERRO','TTS_CANCELLED'}:
            self.record('VOICE_OBSERVED',event=event,event_id=ident)
        with self.lock:
            if event=='TTS_STATE':
                self.tts_busy=detail in {'SYNTHESIZING','PLAYING','CANCELLING'}
            if event == 'TTS_INICIO' and self.state == 'ACTIVE':
                self.speech = ident
                self.speech_correlation = self._new_correlation_id()
                self._movement_record('MOVEMENT_TRIGGER','SPEECH',self.speech_correlation,event_type='TTS_INICIO')
                if self.auto_movements_enabled:
                    hints=getattr(self,'speech_hints',{}).pop(ident,{})
                    self.speech_animation = self.auto_selector.speech_gesture(getattr(response, 'text', ''),**hints)
                    self.speech_emotion = self.auto_selector.last_speech_emotion
                    self.speech_intent = self.auto_selector.last_speech_intent
                    self._movement_record('MOVEMENT_SELECTED','SPEECH',self.speech_correlation,animation=self.speech_animation,
                                          emotion=self.speech_emotion,intent=self.speech_intent)
                else:
                    self.speech_animation='Idle'
                    self.speech_emotion=self.auto_selector.emotion_for(getattr(response,'text',''))
                    self.speech_intent=self.auto_selector.intent_for(getattr(response,'text',''))
                    self._movement_record('MOVEMENT_SKIPPED','SPEECH',self.speech_correlation,reason='automation_disabled')
            elif event in {'TTS_OK','TTS_CANCELLED','TTS_ERRO','TTS_SKIPPED','TTS_STALE_DROPPED'} and ident == self.speech:
                self.speech = None
            elif event == 'TTS_STATE' and detail in {'IDLE','ERROR'}: self.speech = None

    def _open(self):
        self._cleanup()
        self.lease = (RUNTIME/'runtime/panel-owner.lock')
        self.lease.parent.mkdir(exist_ok=True)
        self.lease = self.lease.open('a+b')
        self.lease.seek(0)
        if not self.lease.read(1): self.lease.write(b'0'); self.lease.flush()
        self.lease.seek(0)
        msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
        self.runtime = Runtime()
        self.runtime.start_godot(self.port)
        self.client = ShowClient(port=self.port)
        deadline = time.monotonic()+20
        while True:
            try:
                self.client.connect()
                break
            except (ConnectionError,OSError) as error:
                cause=error
                while cause is not None:
                    if getattr(cause,'winerror',None)==10013:
                        failure=RuntimeError('TCP_LOCAL_ACCESS_DENIED | WinError 10013: acesso a 127.0.0.1 bloqueado nesta sessão; nenhuma restrição foi contornada.')
                        failure.tcp_diagnostic=exception_details(error,phase='godot_connect',port=self.port)
                        raise failure from error
                    cause=cause.__cause__
                if time.monotonic()>deadline or self.stopping: raise
                time.sleep(.15)
        with self.lock:
            if self.state != 'CLOSING': self.state = 'ACTIVE'
        self.client.send_presentation(**self.presentation_preferences)
        self.client.send_auto_mode(self.auto_movements_enabled)
        self.client.send_walk_wave_mode(self.walk_wave_enabled)
        for gesture in WALK_COMBO_GESTURES:
            self.client.send_walk_combo_mode(gesture,self.walk_combo_enabled[gesture])
        self.record('OPEN_CONFIRMED',port=self.port,pid=self.runtime.processes[0].pid)

    def _reconnect_transport(self):
        """Reconnect only to our still-running Godot; never spawn another server."""
        if not self.runtime or not self.runtime.processes or self.runtime.processes[0].poll() is not None:
            return False
        for attempt in range(3):
            if self.stopping or self.state!='ACTIVE':return False
            try:
                self.client.connect()  # closes the previous socket and verifies identity
                provider=getattr(self,'audience_queue_provider',None)
                if provider:self.client.send_audience_queue(provider())
                self._overlay_sent_at=0
                self.presentation_status={}
                self.record('TCP_RECONNECTED',attempt=attempt+1,port=self.port)
                return True
            except (ConnectionError,OSError) as error:
                cause=error
                while cause is not None:
                    if getattr(cause,'winerror',None)==10013:
                        self.record('TCP_RECONNECT_DENIED',port=self.port)
                        return False
                    cause=cause.__cause__
                time.sleep(.15)
        self.record('TCP_RECONNECT_FAILED',port=self.port)
        return False

    def _cleanup(self):
        if self.walk_wave_last_active:
            self.record('WALK_WAVE_END',animation='WalkWave',reason='godot_connection_closed')
            self.walk_wave_last_active=False
        if self.walk_combo_last_active:
            self.record('WALK_COMBO_END',gesture=self.walk_combo_last_active,reason='godot_connection_closed')
            self.walk_combo_last_active=''
        if self.client: self.client.close(); self.client=None
        if self.runtime: self.runtime.close(); self.runtime=None
        if self.lease:
            try:
                self.lease.seek(0); msvcrt.locking(self.lease.fileno(),msvcrt.LK_UNLCK,1)
            except OSError: pass
            self.lease.close(); self.lease=None
        self.speech=None
        self.speech_correlation=None
        self.speech_animation='Idle'
        self.speech_emotion='calm'
        self.speech_intent='comment'
        self.auto_selector.set_idle_cycle(self.idle_walk_seconds,self.idle_rest_seconds)
        self.pending_movements.clear()
        self.active_movement=None
        self.last_status_key=None
        self.last_scenery_moving=None
        self.walk_context=None
        self.walking_requested=False
        self.presentation_status={}
        self.external_paused=False
        self.external_override_before_pause=False
        self.manual_override=False
        self.manual_override_before_pause=False
        self.manual_paused=False
        self.auto_commands.clear()
        self.auto_idle_walking=False
        self.manual_current=None
        self.manual_state='Aguardando Godot'

    def _send(self, command, ident=None):
        self.client.send_event(command)
        self.record('TCP_SENT',command=command,event_id=ident)

    def manual_animation(self, animation, repeat=False):
        if animation not in ANIMATIONS or type(repeat) is not bool:
            return False
        with self.lock:
            if self.state != 'ACTIVE' or self.manual_paused or self.external_paused:
                self.error = 'Abra o ZUKO 3D antes de enviar movimentos.'
                return False
            self._discard_auto()
            correlation_id=self._new_correlation_id()
            self._movement_record('MOVEMENT_TRIGGER','MANUAL',correlation_id,command='animate')
            try: self.manual_commands.put_nowait(('animate', animation, repeat, correlation_id))
            except queue.Full:
                self.error = 'Fila manual cheia.'
                self._movement_record('MOVEMENT_SKIPPED','MANUAL',correlation_id,reason='queue_full',animation=animation)
                return False
            self._movement_record('MOVEMENT_SELECTED','MANUAL',correlation_id,animation=animation,repeat=repeat)
            if animation in LOCOMOTION:self.walking_requested=True
            elif repeat or animation == 'Idle': self.walking_requested = False
            self.manual_override = True
            self.manual_awaiting_status = True
            self.manual_confirmed = False
            self.manual_current = animation
            self.manual_state = 'Solicitado: ' + animation + ' (sem retorno do estado do Godot)'
        return True

    def manual_control(self, command):
        if command not in {'stop', 'idle', 'pause', 'resume'}: return False
        with self.lock:
            if self.state != 'ACTIVE': return False
            if command == 'resume' and (not self.manual_paused or self.external_paused): return False
            self._discard_auto()
            correlation_id=self._new_correlation_id()
            animation='Idle' if command=='idle' else self.presentation_status.get('animation') if command=='resume' else None
            self._movement_record('MOVEMENT_TRIGGER','MANUAL',correlation_id,command=command)
            if animation:self._movement_record('MOVEMENT_SELECTED','MANUAL',correlation_id,animation=animation)
            try: self.manual_commands.put_nowait((command, None, None, correlation_id))
            except queue.Full:
                self.error = 'Fila manual cheia.'
                self._movement_record('MOVEMENT_SKIPPED','MANUAL',correlation_id,reason='queue_full',animation=animation)
                return False
            if command in {'idle','stop'}: self.walking_requested = False
            if command == 'idle':
                # Keep manual priority until the Idle command reaches Godot.
                self.manual_state = 'Solicitado: Idle'
            elif command in {'stop', 'pause'}:
                if command=='pause':self.manual_override_before_pause=self.manual_override
                self.manual_override = True
                self.manual_paused = command == 'pause'
                if command == 'stop': self.manual_current = None
                self.manual_state = 'Parado' if command == 'stop' else 'Pausado'
            elif command == 'resume':
                self.manual_paused = False
                self.manual_override=self.manual_override_before_pause
                self.manual_state = 'Retomado'
        return True

    def set_presentation(self, **options):
        with self.lock:
            if 'walking' in options and self.state != 'ACTIVE': return False
            if options.get('walking') and (self.manual_paused or self.external_paused): return False
            self.presentation_preferences.update({key:value for key,value in options.items() if key != 'walking'})
            if self.state != 'ACTIVE': return True
            if options.get('walking') == self.walking_requested and set(options) == {'walking'}: return True
            correlation_id=self._new_correlation_id() if 'walking' in options else None
            animation='Walk' if options.get('walking') else 'Idle'
            if correlation_id:
                self._movement_record('MOVEMENT_TRIGGER','MANUAL',correlation_id,command='walking',enabled=bool(options.get('walking')))
                self._movement_record('MOVEMENT_SELECTED','MANUAL',correlation_id,animation=animation)
            try: self.manual_commands.put_nowait(('presentation', dict(options), None, correlation_id))
            except queue.Full:
                if correlation_id:self._movement_record('MOVEMENT_SKIPPED','MANUAL',correlation_id,reason='queue_full',animation=animation)
                return False
            if 'walking' in options:
                self.walking_requested = options['walking']
                self.manual_current = 'Walk' if options['walking'] else 'Idle'
                self.manual_override = False
                self._discard_auto()
            return True

    def _discard_auto(self):
        while True:
            try: self.commands.get_nowait()
            except queue.Empty: break
        self.auto_commands.clear()

    def _run(self):
        reaction_until = 0
        sent_speech = None
        sent_speech_correlation = None
        self.reaction_until = 0
        try:
            while not self.stopping:
                now=time.monotonic()
                command=None
                try:
                    if self.state == 'CLOSING':
                        self._cleanup()
                        while not self.commands.empty():
                            try:self.commands.get_nowait()
                            except queue.Empty:break
                        while not self.manual_commands.empty():
                            try:self.manual_commands.get_nowait()
                            except queue.Empty:break
                        self.state='OFF';reaction_until=0;sent_speech=None;sent_speech_correlation=None
                        self.record('CLOSED_ONLY_NPC')
                    if self.state=='ACTIVE' and self.runtime and self.runtime.processes[0].poll() is not None:
                        self._cleanup();self.state='OFF';reaction_until=0;sent_speech=None;sent_speech_correlation=None
                        self.record('NPC_WINDOW_CLOSED')
                    if self.state == 'ACTIVE':
                        provider=getattr(self,'audience_queue_provider',None)
                        if provider and now-getattr(self,'_overlay_sent_at',0)>=.25:
                            snapshot=provider()
                            self.client.send_audience_queue(snapshot)
                            self._overlay_sent_at=now
                            key=(id(self.client),snapshot['version'])
                            if key!=getattr(self,'_overlay_key',None):
                                self.record('AUDIENCE_OVERLAY_SENT',version=snapshot['version'],count=len(snapshot['rows']),extra=snapshot['extra'])
                                self._overlay_key=key
                        status = self.client.poll_status()
                        if status:
                            self._observe_presentation_status(status)
                            ack=status.get('audience_queue',{})
                            ack_key=(ack.get('session'),ack.get('version'))
                            if ack.get('session') and ack_key!=getattr(self,'_overlay_ack_key',None):
                                self.record('AUDIENCE_OVERLAY_CONFIRMED',version=ack.get('version'),visible=ack.get('visible'))
                                self._overlay_ack_key=ack_key
                        external = bool(self.pause_provider())
                        if external != self.external_paused:
                            was_blocked=self.external_override_before_pause
                            if external:self.external_override_before_pause=self.manual_override
                            self.external_paused = external
                            effective_paused=external or self.manual_paused
                            previous_effective=(not external) or self.manual_paused
                            if effective_paused != previous_effective:
                                self.client.send_control('pause' if effective_paused else 'resume')
                            if not external and not self.manual_paused and was_blocked is not None:
                                self.manual_override=was_blocked
                    if self.state=='ACTIVE' and self.speech != sent_speech:
                        if sent_speech:
                            self.client.send_event('idle',speech_end=True)
                            self.record('SPEECH_END',event_id=sent_speech)
                            self._movement_record('MOVEMENT_TCP_SENT','SPEECH',sent_speech_correlation,command='speech_end')
                        sent_speech=self.speech
                        sent_speech_correlation=self.speech_correlation
                        if sent_speech:
                            # Playback state always reaches Godot; gesture autonomy remains optional.
                            gesture = self.speech_animation if self.auto_movements_enabled and not self.manual_override and not self.manual_paused and not self.external_paused else 'Idle'
                            self.client.send_event('talk',speaking=True,gesture=gesture)
                            self.record('SPEECH_START',event_id=sent_speech,gesture=gesture,
                                        emotion=self.speech_emotion,intent=self.speech_intent)
                            self._queue_movement_confirmation(sent_speech_correlation,'SPEECH',gesture)
                            self._movement_record('MOVEMENT_TCP_SENT','SPEECH',sent_speech_correlation,command='talk',animation=gesture)
                    manual = None
                    if self.state == 'ACTIVE':
                        try: manual = self.manual_commands.get_nowait()
                        except queue.Empty: pass
                    if manual:
                        action, animation, repeat, correlation_id = manual
                        if action == 'animate':
                            self.client.send_animation(animation, repeat)
                            self._queue_movement_confirmation(correlation_id,'MANUAL',animation)
                            self._movement_record('MOVEMENT_TCP_SENT','MANUAL',correlation_id,command='animate',animation=animation,repeat=repeat)
                        elif action == 'presentation':
                            self.client.send_presentation(**animation)
                            if 'walking' in animation:
                                clip='Walk' if animation['walking'] else 'Idle'
                                self._queue_movement_confirmation(correlation_id,'MANUAL',clip)
                                self._movement_record('MOVEMENT_TCP_SENT','MANUAL',correlation_id,command='presentation',animation=clip,enabled=bool(animation['walking']))
                        elif action == 'auto_mode': self.client.send_auto_mode(animation)
                        elif action == 'walk_wave_mode': self.client.send_walk_wave_mode(animation)
                        elif action == 'walk_combo_mode': self.client.send_walk_combo_mode(*animation)
                        else:
                            self.client.send_control(action)
                            clip=animation if action=='idle' else self.presentation_status.get('animation') if action=='resume' else None
                            if action in {'idle','resume'} and clip:
                                self._queue_movement_confirmation(correlation_id,'MANUAL',clip)
                            self._movement_record('MOVEMENT_TCP_SENT','MANUAL',correlation_id,command=action,animation=clip)
                        if action == 'idle':
                            with self.lock:
                                self.manual_override = False
                                self.manual_paused = False
                                self.manual_current = 'Idle'
                        self.record('MANUAL_SENT',command=action,animation=animation,repeat=repeat)
                        reaction_until=time.monotonic()+.05
                        continue
                    if (self.state=='ACTIVE' and self.auto_movements_enabled and not self.manual_override
                        and not self.manual_paused and not self.external_paused and not self.speech
                        and not self.godot_speaking and not self.tts_busy
                        and now>=reaction_until and not self.presentation_status.get('reacting',False)):
                        automatic=None
                        with self.lock:
                            if self.auto_commands:automatic=self.auto_commands.pop(0)
                        if automatic is None:
                            with self.lock: idle_move=self.auto_selector.idle_action()
                            if idle_move is not None:
                                correlation_id=self._new_correlation_id()
                                self._movement_record('MOVEMENT_TRIGGER','IDLE',correlation_id,event_type='IDLE_TIMER')
                                self._movement_record('MOVEMENT_SELECTED','IDLE',correlation_id,animation=idle_move.animation,event_type='IDLE_TIMER')
                                automatic=(idle_move.priority,now,idle_move.animation,correlation_id,idle_move.cooldown,'IDLE')
                        if automatic:
                            _,_,animation,correlation_id,cooldown,origin=automatic
                            actual_animation='WalkWave' if animation=='Walk' and self.walk_wave_enabled else animation
                            self.client.send_auto_animation(actual_animation)
                            self._queue_movement_confirmation(correlation_id,origin,actual_animation)
                            self._movement_record('MOVEMENT_TCP_SENT',origin,correlation_id,command='auto_animate',animation=actual_animation)
                            self.record('AUTO_MOVEMENT_SENT',animation=actual_animation,event_id=correlation_id)
                            self.auto_idle_walking=animation=='Walk' and origin=='IDLE'
                            reaction_until=now+max(.15,cooldown)
                            continue
                    if self.manual_override:
                        try: command,at,ident=self.commands.get(timeout=.04)
                        except queue.Empty: pass
                        command=None
                    elif now>=reaction_until:
                        try:command,at,ident=self.commands.get(timeout=.04)
                        except queue.Empty:pass
                    else:time.sleep(.04)
                    if command=='open':
                        self._open();reaction_until=0;sent_speech=None;sent_speech_correlation=None
                    elif command in {'comment','gift','follow'} and self.state=='ACTIVE' and now-at<15:
                        self._send(command,ident)
                        reaction_until=time.monotonic()+{'gift':.65,'comment':2.15,'follow':2.2}[command]
                        self.reaction_until=reaction_until
                except Exception as error:
                    if isinstance(error,(ConnectionError,OSError)) and self.state=='ACTIVE' and self._reconnect_transport():
                        continue
                    transport=exception_details(error,phase='bridge_worker',port=getattr(self,'port',18765))
                    processes=getattr(getattr(self,'runtime',None),'processes',[])
                    if processes:transport['godot_pid']=processes[0].pid
                    self._cleanup();self.state='ERROR';self.error=type(error).__name__+': '+str(error)[:350]
                    self.record('ERROR',reason=self.error,transport=transport)
        finally:self._cleanup()

    def _poll(self):
        labels={'OFF':'ABRIR ZUKO 3D','STARTING':'ABRINDO ZUKO…','ACTIVE':'ZUKO ATIVO','CLOSING':'FECHANDO NPC…','ERROR':'TENTAR NPC 3D'}
        self.button.configure(text=labels[self.state],state='disabled' if self.state in {'STARTING','CLOSING'} else 'normal')
        self.close_button.configure(state='normal' if self.state in {'ACTIVE','ERROR'} else 'disabled')
        if self.error:
            self.button.configure(text='TENTAR NPC 3D')
        if hasattr(self, 'walk_button'):
            self.walk_button.configure(text='PARAR CAMINHADA' if self.walking_requested else 'INICIAR CAMINHADA', state='normal' if self.state == 'ACTIVE' else 'disabled')
            status = self.presentation_status
            if status and hasattr(self, 'live_mode_var'): self.live_mode_var.set(status.get('live',False))
            self.walk_status_label.configure(text=('Godot confirmou: '+('caminhada ativa' if status.get('walking') else 'caminhada parada')+' · '+str(status.get('animation',''))+(' · PAUSADO' if status.get('paused') else '')+' · '+('LIVE 9:16' if status.get('live') else 'desenvolvimento')) if status else 'Aguardando conexão e confirmação do Godot.')
        if hasattr(self, 'movement_status'):
            connection = 'conectado' if self.state == 'ACTIVE' else 'desconectado'
            actual = self.presentation_status.get('animation')
            source=self.presentation_status.get('source','')
            active=('Animação confirmada: '+actual+(' · '+source if source else '')) if actual else self.manual_state
            automatic=self.presentation_status.get('automatic',self.auto_movements_enabled)
            self.movement_status.configure(text='Godot: '+connection+' · AUTO '+('ligado' if automatic else 'desligado')+' · '+active)
        if hasattr(self,'walk_wave_button'):
            self.walk_wave_var.set(self.walk_wave_enabled)
            self.walk_wave_button.configure(text='WALK + WAVE — '+('LIGADO' if self.walk_wave_enabled else 'DESLIGADO'))
            if self.state!='ACTIVE':
                detail='Preferência salva; aguardando abrir o personagem.'
            elif not self.presentation_status.get('walk_wave_available',False):
                detail='Indisponível: '+(self.presentation_status.get('walk_wave_error') or 'confira Diagnóstico.')
            elif self.presentation_status.get('walk_wave_active',False):
                detail='Godot confirmou: Walk + Wave ativo; o cenário acompanha a caminhada.'
            elif self.walk_wave_enabled:
                detail='Habilitado para a próxima caminhada automática.' if self.auto_movements_enabled else 'Habilitado; requer MOVIMENTOS AUTOMÁTICOS ligado.'
            else:
                detail='Desativado; a caminhada automática usará Walk.'
            self.walk_wave_status.configure(text=detail)
        if hasattr(self,'walk_combo_buttons'):
            for gesture in WALK_COMBO_GESTURES:
                enabled=self.walk_combo_enabled.get(gesture,False)
                self.walk_combo_vars[gesture].set(enabled)
                self.walk_combo_buttons[gesture].configure(text='WALK + '+gesture.upper()+' — '+('LIGADO' if enabled else 'DESLIGADO'))
                if self.state!='ACTIVE':
                    detail='Preferência salva; aguardando abrir o personagem.' if enabled else 'Combinação local desativada por padrão.'
                elif not self.presentation_status.get('walk_combo_available',{}).get(gesture,False):
                    detail='Indisponível: '+self.presentation_status.get('walk_combo_errors',{}).get(gesture,'confira Diagnóstico.')
                elif self.presentation_status.get('walk_combo_active')==gesture:
                    detail='Godot confirmou: Walk + '+gesture+' ativo; cenário em movimento.'
                elif enabled:
                    detail='Habilitado para a próxima caminhada; confirmação no Godot pendente.' if gesture in self.walk_combo_pending else 'Habilitado para a próxima caminhada automática.'
                else:
                    detail='Desativado; a ação usa a animação original.'
                self.walk_combo_statuses[gesture].configure(text=detail)
        if not self.stopping: self.root.after(150,self._poll)

    def shutdown(self):
        self.stopping=True
