"""Reviewable aggregate evidence and a cancellable, bounded reflection worker."""
from collections import OrderedDict, deque
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import os
import re
import threading
import uuid

from zuko_v3_content import FRAMES, TOPICS

FRAME_FIELDS={'completed','words','speech_seconds','real_events','related_questions','challenge_responses'}
TOTAL_FIELDS={'completed','COMMENT','GIFT','FOLLOW','LIKE','related_questions','challenge_responses',
              'duplicates','simulated','repetitions','audience_completed'}
ERROR_FIELDS={'TTS_ERRO','TTS_CANCELLED','TTS_STALE_DROPPED','TTS_SKIPPED','PROVIDER_ERROR',
              'REPEAT_GUARD','PENDING_EXPIRED','DIRECTOR_DISCARDED','OTHER'}
REFLECTION_ACTIONS={'maintain','change_topic','reduce_energy','increase_energy','create_challenge',
                    'resume_question','avoid_repeat'}


def _counts(value, allowed):
    if not isinstance(value,dict) or set(value)-allowed:raise ValueError('EVIDENCE_FIELDS')
    if any(type(number) not in (int,float) or not math.isfinite(number) or not 0<=number<=1e9 for number in value.values()):
        raise ValueError('EVIDENCE_NUMBER')
    return dict(value)


def _summary(value):
    allowed={'source_observed','frames','topics','totals','technical_failures','association_only'}
    if not isinstance(value,dict) or set(value)!=allowed or type(value['source_observed']) is not bool or value['association_only'] is not True:
        raise ValueError('EVIDENCE_SCHEMA')
    frames=value['frames'];topics=value['topics']
    if not isinstance(frames,dict) or set(frames)-set(FRAMES):raise ValueError('EVIDENCE_FRAME')
    if not isinstance(topics,list) or len(topics)>len(TOPICS) or any(topic not in TOPICS for topic in topics):
        raise ValueError('EVIDENCE_TOPIC')
    return {'source_observed':value['source_observed'],
        'frames':{name:_counts(row,FRAME_FIELDS) for name,row in frames.items()},
        'topics':list(dict.fromkeys(topics)), 'totals':_counts(value['totals'],TOTAL_FIELDS),
        'technical_failures':_counts(value['technical_failures'],ERROR_FIELDS),'association_only':True}


def _assessment(summary):
    promising=[frame for frame,row in summary['frames'].items() if summary['source_observed'] and
               row.get('completed',0)>=4 and row.get('related_questions',0)+row.get('challenge_responses',0)>=2]
    repetitive=summary['totals'].get('repetitions',0)>0
    return {'promising_frames':promising,'repetition_observed':repetitive,
            'hypotheses':['avoid_repeat'] if repetitive else ['create_challenge'] if promising else ['maintain'],
            'association_only':True}


def _validate_assessment(value):
    if (not isinstance(value,dict) or set(value)!={'promising_frames','repetition_observed','hypotheses','association_only'} or
        not isinstance(value['promising_frames'],list) or len(value['promising_frames'])>len(FRAMES) or
        any(frame not in FRAMES for frame in value['promising_frames']) or
        type(value['repetition_observed']) is not bool or value['association_only'] is not True or
        not isinstance(value['hypotheses'],list) or len(value['hypotheses'])>3 or
        any(action not in REFLECTION_ACTIONS for action in value['hypotheses'])):
        raise ValueError('STORE_ASSESSMENT')


class EvidenceStore:
    MAX_BYTES=256*1024

    def __init__(self, path=None, config=None):
        self.path=Path(path) if path else None;self.config=config or {}
        self.lock=threading.RLock();self.error='';self.disk_hash=None
        self.data={'version':1,'sessions':[],'patterns':{}}
        if self.path and self.path.exists():
            try:
                raw=self.path.read_bytes()
                if len(raw)>self.MAX_BYTES:raise ValueError('STORE_SIZE')
                candidate=json.loads(raw)
                self._validate(candidate);self.data=candidate
                self.disk_hash=hashlib.sha256(raw).hexdigest()
            except (OSError,ValueError,TypeError,KeyError):self.error='STORE_INVALID_REVIEW_REQUIRED'

    def _validate(self,data):
        if not isinstance(data,dict) or set(data)!={'version','sessions','patterns'} or data['version']!=1:
            raise ValueError('STORE_SCHEMA')
        if not isinstance(data['sessions'],list) or len(data['sessions'])>50:raise ValueError('STORE_SESSIONS')
        for row in data['sessions']:
            if not isinstance(row,dict) or set(row) not in ({'session_id','summary'},{'session_id','summary','assessment'}) or not re.fullmatch(r'[a-f0-9]{32}',str(row['session_id'])):
                raise ValueError('STORE_SESSION')
            _summary(row['summary'])
            if 'assessment' in row:_validate_assessment(row['assessment'])
        patterns=data['patterns']
        if not isinstance(patterns,dict) or set(patterns)-set(FRAMES):raise ValueError('STORE_PATTERNS')
        for row in patterns.values():
            if not isinstance(row,dict) or set(row)!={'status','sessions','basis'} or row['status'] not in {'pending','approved','rejected'} or row['basis']!='temporal_association':
                raise ValueError('STORE_PATTERN')
            if not isinstance(row['sessions'],list) or len(row['sessions'])>50 or any(not re.fullmatch(r'[a-f0-9]{32}',str(ident)) for ident in row['sessions']):
                raise ValueError('STORE_PATTERN_SESSIONS')

    def _save(self):
        if self.error:raise ValueError('STORE_REVIEW_REQUIRED')
        self._validate(self.data)
        raw=json.dumps(self.data,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        if len(raw)>self.MAX_BYTES:raise ValueError('STORE_SIZE')
        if self.path:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            lock_path=self.path.with_suffix('.lock')
            descriptor=os.open(lock_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            temporary=self.path.with_suffix('.tmp.'+uuid.uuid4().hex)
            try:
                current=hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None
                if current!=self.disk_hash:raise ValueError('STORE_CONCURRENT_UPDATE')
                with temporary.open('wb') as handle:
                    handle.write(raw);handle.flush();os.fsync(handle.fileno())
                os.replace(temporary,self.path)
                self.disk_hash=hashlib.sha256(raw).hexdigest()
            finally:
                temporary.unlink(missing_ok=True)
                os.close(descriptor);lock_path.unlink(missing_ok=True)

    def add_session(self, ident, summary):
        with self.lock:
            before=deepcopy(self.data)
            try:
                if not re.fullmatch(r'[a-f0-9]{32}',str(ident)):raise ValueError('SESSION_ID')
                if any(row['session_id']==ident for row in self.data['sessions']):return False
                clean=_summary(summary)
                self.data['sessions'].append({'session_id':ident,'summary':clean,'assessment':_assessment(clean)})
                history=max(3,min(50,int(self.config.get('history_sessions',20))))
                self.data['sessions']=self.data['sessions'][-history:]
                minimum=max(2,min(10,int(self.config.get('minimum_sessions',3))))
                samples=max(2,min(100,int(self.config.get('minimum_samples',4))))
                for frame in FRAMES:
                    evidence=[]
                    for row in self.data['sessions']:
                        item=row['summary'];metrics=item['frames'].get(frame,{})
                        if (item['source_observed'] and metrics.get('completed',0)>=samples
                                and metrics.get('related_questions',0)+metrics.get('challenge_responses',0)>=2):
                            evidence.append(row['session_id'])
                    if len(set(evidence))>=minimum:
                        previous=self.data['patterns'].get(frame,{})
                        self.data['patterns'][frame]={'status':previous.get('status',
                            'pending' if self.config.get('manual_review',True) else 'approved'),
                            'sessions':list(dict.fromkeys(evidence)),'basis':'temporal_association'}
                self._save();return True
            except (OSError,ValueError,TypeError,KeyError) as error:
                self.data=before;self.error=type(error).__name__+'_STORE_WRITE_BLOCKED';return False

    def review(self,frame,approve):
        with self.lock:
            if frame not in self.data['patterns'] or type(approve) is not bool:return False
            before=deepcopy(self.data)
            self.data['patterns'][frame]['status']='approved' if approve else 'rejected'
            try:self._save();return True
            except (OSError,ValueError):self.data=before;self.error='STORE_REVIEW_WRITE_BLOCKED';return False

    def weights(self):
        with self.lock:
            return {frame:1.1 for frame,row in self.data['patterns'].items() if row['status']=='approved'}

    def snapshot(self):
        with self.lock:
            return {'sessions':len(self.data['sessions']),'patterns':deepcopy(self.data['patterns']),
                    'error':self.error,'approved':len(self.weights()),
                    'last_assessment':deepcopy(self.data['sessions'][-1].get('assessment')) if self.data['sessions'] else None}


def validate_reflection(value):
    if isinstance(value,str):
        if len(value)>4096:raise ValueError('REFLECTION_SIZE')
        value=json.loads(value)
    if not isinstance(value,dict) or set(value)!={'action','topic','energy','reason_code'}:
        raise ValueError('REFLECTION_SCHEMA')
    if any(not isinstance(item,str) for item in value.values()):raise ValueError('REFLECTION_TYPE')
    if value['action'] not in REFLECTION_ACTIONS or value['topic'] not in TOPICS:
        raise ValueError('REFLECTION_ACTION')
    if value['energy'] not in {'lower','keep','higher'} or value['reason_code'] not in {'TIMING_SIGNALS','REPETITION','CONTINUITY','INSUFFICIENT_DATA'}:
        raise ValueError('REFLECTION_ENUM')
    return dict(value)


def local_reflection(context):
    signals=context.get('engagement',{})
    repeated=context.get('summary',{}).get('totals',{}).get('repetitions',0)
    action='avoid_repeat' if repeated else 'create_challenge' if signals.get('related_questions',0)>1 else 'maintain'
    reason='REPETITION' if repeated else 'TIMING_SIGNALS' if signals.get('data_status')=='OBSERVED' else 'INSUFFICIENT_DATA'
    return {'action':action,'topic':context.get('topic') if context.get('topic') in TOPICS else TOPICS[0],
            'energy':'keep','reason_code':reason}


class ReflectionWorker:
    def __init__(self):
        self.lock=threading.RLock();self.worker=None;self.cancel_event=threading.Event()
        self.epoch=0;self.results=deque(maxlen=2);self.cache=OrderedDict();self.last_error=''

    def start(self,context,model=None):
        payload=json.dumps(context,sort_keys=True,separators=(',',':'))
        if len(payload)>16000:return False
        key=hashlib.sha256(payload.encode()).hexdigest()
        with self.lock:
            if self.worker and self.worker.is_alive():return False
            self.cancel_event=threading.Event();cancel=self.cancel_event;epoch=self.epoch
            if key in self.cache:
                self.results.append(dict(self.cache[key]));return True
            def run():
                suggestion=local_reflection(context)
                try:
                    if model and not cancel.is_set():
                        proposed=model(context,cancel.is_set)
                        if proposed is not None:suggestion=validate_reflection(proposed)
                except Exception as error:
                    self.last_error=type(error).__module__+'.'+type(error).__name__
                with self.lock:
                    if cancel.is_set() or epoch!=self.epoch:return
                    suggestion=validate_reflection(suggestion)
                    self.results.append(suggestion);self.cache[key]=suggestion
                    while len(self.cache)>16:self.cache.popitem(last=False)
            self.worker=threading.Thread(target=run,name='zuko-v3-reflection',daemon=True)
            self.worker.start();return True

    def poll(self):
        with self.lock:
            value=self.results.pop() if self.results else None
            self.results.clear();return value

    def cancel(self):
        with self.lock:
            self.cancel_event.set();self.epoch+=1;self.results.clear()

    def close(self):
        self.cancel()
        worker=self.worker
        if worker and worker is not threading.current_thread():worker.join(timeout=5)
        return not worker or not worker.is_alive()
