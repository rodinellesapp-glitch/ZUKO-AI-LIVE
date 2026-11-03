"""Bounded RAM coordination; Audience/Moderator/Director retain their authority."""
import re
import time
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from threading import RLock
from live_entertainment import normalized
from live_cohost import current_intent
from live_platform_adapter import safe_name
from zuko_public_name import public_name
from live_reactions import reaction_comment, reaction_details

LEVELS={0:(2,8),1:(4,18),2:(8,30),3:(15,50),4:(40,90)}

@dataclass
class ViewerContext:
    author: str
    last_seen: float
    last_message: str=''
    last_message_at: float=0.
    last_topic: str='GENERAL_LIVE'
    last_question: str=''
    last_jarvis_reply: str=''
    recent_interactions: deque=field(default_factory=lambda:deque(maxlen=3))
    recent_gift_event: str=''
    recent_reaction: tuple=()
    greeted: bool=False
    interaction_count: int=0

@dataclass(frozen=True)
class FlowDecision:
    action: str
    level: int=0
    score: int=0
    reply: str=''
    event_ids: tuple=()
    author: str=''
    priority: str='NORMAL'
    created_at: float=0.
    evidence: tuple=()
    reason: str=''
    source_kind: str=''

    def writer_hint(self):
        lo,hi=LEVELS[self.level]
        return f'LIVE_FLOW: ação {self.action}; nível {self.level}; normalmente {lo}–{hi} palavras. Responda primeiro; sem pergunta obrigatória. Humor leve não é fato real. Não invente significado, experiência física ou ações do apresentador.'

class LiveFlowEngine:
    def __init__(self,clock=time.monotonic,batch_seconds=3):
        if not 2<=batch_seconds<=4:raise ValueError('Batch deve ficar entre 2 e 4 segundos')
        self.clock=clock;self.batch_seconds=batch_seconds;self.lock=RLock();self.reset()

    def reset(self):
        with self.lock:
            from live_writer import RunningGags
            if not hasattr(self,'running_gags'):self.running_gags=RunningGags(self.clock)
            else:self.running_gags.reset()
            self.recent=deque(maxlen=500);self.viewers=OrderedDict();self.threads=OrderedDict()
            self.seen=OrderedDict();self.batches=OrderedDict();self.greeted_viewers=OrderedDict();self.counts=Counter()
            self._join_greeting_pending=OrderedDict()
            self.pace='QUIET';self.transitions=deque(maxlen=100);self.logs=deque(maxlen=100)
            self.constructions=deque(maxlen=20);self.serial=0;self.wait_host_until=0.
            self.feedback=deque(maxlen=300)

    def _expire(self):
        now=self.clock()
        while self.recent and now-self.recent[0][0]>30:self.recent.popleft()
        for author,row in list(self.viewers.items()):
            if now-row.last_seen>300:del self.viewers[author]
        for topic,row in self.threads.items():
            if now-row['at']>300:row['status']='CLOSED'

    def pace_snapshot(self,tts=None):
        with self.lock:
            self._expire();tts=tts or {};n=len(self.recent)
            authors=len({a for _,a,_ in self.recent if a})
            events=sum(k not in {'CHAT_MESSAGE','SPOKEN_RESPONSE'} for _,_,k in self.recent)
            depth=tts.get('TTS_QUEUE_DEPTH',0)
            pace='HYPER' if n>=40 or depth>=4 else 'BUSY' if n>=20 or events>=10 or depth>=3 else 'NORMAL' if n>=5 or authors>=5 or depth else 'QUIET'
            if pace!=self.pace:
                self.transitions.append((self.clock(),pace));self.logs.append('LIVE_PACE | '+pace)
            self.pace=pace
            return {'LIVE_PACE':pace,'FLOW_MESSAGES_30S':sum(k=='CHAT_MESSAGE' for _,_,k in self.recent),
                'FLOW_RESPONSES_30S':sum(k=='SPOKEN_RESPONSE' for _,_,k in self.recent),
                'FLOW_AUTHORS_30S':authors,'FLOW_EVENTS_30S':events,**self.counts}

    def _viewer(self,event):
        author=event.author_id or event.author_name
        row=self.viewers.setdefault(author,ViewerContext(author,self.clock()))
        previous=row.last_message;previous_at=row.last_message_at
        row.last_seen=self.clock();row.last_message_at=row.last_seen;row.interaction_count+=1
        # Short lived summaries; omit obvious sensitive numeric/contact material.
        row.last_message=re.sub(r'\b\d{5,}\b|\S+@\S+','[omitido]',event.text[:160])
        if '?' in event.text:row.last_question=row.last_message
        if event.event_type=='GIFT_EVENT' and event.confirmed:row.recent_gift_event=event.event_id
        row.recent_reaction=tuple('FLOWER_TEXT' if kind=='FLOWER' else kind for kind in reaction_details(event.text)['categories'])
        self.viewers.move_to_end(author)
        while len(self.viewers)>20:self.viewers.popitem(last=False)
        return row,previous,previous_at

    def _thread(self,row,text,topic):
        value=normalized(text);explicit=bool(re.search(r'\b(vamos falar|agora|mudando de assunto|quero falar)\b',value))
        nouns={'danca':'dança','futebol':'futebol','carros':'carros','celular':'celular','games':'games','musica':'música'}
        label='humor' if current_intent(text)=='JOKE_REQUEST' else next((v for k,v in nouns.items() if re.search(r'\b'+k+r'\b',value)),None)
        if label and (explicit or row.last_topic=='GENERAL_LIVE'):
            for old in self.threads.values():
                if old['status']=='ACTIVE':old['status']='PAUSED'
            row.last_topic=label;self.threads[label]={'status':'ACTIVE','at':self.clock()}
        elif row.last_topic=='GENERAL_LIVE':row.last_topic=topic
        if row.last_topic in self.threads:self.threads[row.last_topic]['at']=self.clock()
        while len(self.threads)>8:self.threads.popitem(last=False)

    def _batch(self,event,kind):
        key=(kind,event.gift_type if kind=='GIFT' else '')
        if key not in self.batches and len(self.batches)>=8:
            self.counts['registered_only']+=1
            return FlowDecision('REGISTER_ONLY',reason='BATCH_CAPACITY')
        b=self.batches.setdefault(key,{'at':self.clock(),'authors':OrderedDict(),'ids':[], 'quantity':0,'quantity_known':True,'evidence':[]})
        if len(b['evidence'])<20:
            b['evidence'].append(dict(id=event.event_id,type=event.event_type,author=safe_name(event.author_name),gift=safe_name(event.gift_type or ''),quantity=event.gift_quantity))
        author=event.author_id or event.author_name
        if len(b['authors'])<20:b['authors'][author]=public_name(event.author_name)
        if len(b['ids'])<200:b['ids'].append(event.event_id)
        b['quantity_known'] &= event.gift_quantity is not None
        if event.gift_quantity is not None:b['quantity']+=event.gift_quantity
        self.counts['batched']+=1
        if kind=='VIEWER_JOIN':self.counts['JOIN_EVENTS_GROUPED']+=1
        return FlowDecision('BATCH',event_ids=(event.event_id,),author=author,created_at=self.clock(),
                            reason='BATCHED_'+kind,source_kind=kind)

    def _line(self,options):
        value=next((x for x in options if x not in self.constructions),options[self.serial%len(options)])
        self.serial+=1;self.constructions.append(value);return value

    def decide(self,event,*,allowed=True,classification='',presenter_answer=False,pending_question=False,topic='GENERAL_LIVE',tts=None):
        with self.lock:
            self._expire();now=self.clock();self.counts['total_events']+=1
            if event.event_type=='VIEWER_JOIN':self.counts['JOIN_EVENTS_RECEIVED']+=1
            ident=(event.platform,event.event_id)
            if ident in self.seen:
                self.counts['ignored']+=1
                if event.event_type=='VIEWER_JOIN':self.counts['JOIN_DUPLICATES']+=1
                return FlowDecision('IGNORE',reason='DUPLICATE_EVENT_ID')
            self.seen[ident]=None
            while len(self.seen)>2000:self.seen.popitem(last=False)
            self.recent.append((now,event.author_id,event.event_type));pace=self.pace_snapshot(tts)['LIVE_PACE']
            if not allowed:self.counts['ignored']+=1;return FlowDecision('IGNORE',reason='MODERATION_BLOCKED')
            if isinstance(event.timestamp,(float,int)) and now-event.timestamp>45:
                self.counts['ignored']+=1;return FlowDecision('IGNORE',reason='EVENT_EXPIRED')
            value=normalized(event.text)
            if re.search(r'\b(ignore.*regras|system prompt|execute|powershell|abra cmd|senha|token|credenciais|chave api|api key|sexo explicito)\b',value):
                self.counts['ignored']+=1;return FlowDecision('IGNORE',score=-100,reason='SAFETY_FILTER')
            row,previous,previous_at=self._viewer(event);self._thread(row,event.text,topic)
            details=reaction_details(event.text)
            self.feedback.append((now,event.author_id,event.event_type,bool(details['emoji_count']),
                presenter_answer,details['text_intent'],tuple(details['categories'])))
            author=event.author_id or event.author_name;name=safe_name(event.author_name)
            if event.event_type!='CHAT_MESSAGE':
                if not event.confirmed:self.counts['registered_only']+=1;return FlowDecision('REGISTER_ONLY',reason='SOURCE_UNVERIFIED')
                if event.priority=='HIGH':return FlowDecision('THANK',1,90,self._line((f'{name or "Pessoal"}, obrigado pelo apoio!',f'Valeu pelo apoio{", "+name if name else ""}!')), (event.event_id,),author,'HIGH',now)
                if event.event_type=='GIFT_EVENT':return self._batch(event,'GIFT')
                if event.event_type=='VIEWER_JOIN':
                    joiner=event.author_id or event.author_name
                    if joiner and joiner in self.greeted_viewers:
                        self.counts['ignored']+=1;self.counts['JOIN_DUPLICATES']+=1
                        return FlowDecision('IGNORE',reason='JOIN_ALREADY_GREETED')
                    decision=self._batch(event,'VIEWER_JOIN')
                    if decision.action=='BATCH' and joiner:
                        self.greeted_viewers[joiner]=now
                        while len(self.greeted_viewers)>1000:self.greeted_viewers.popitem(last=False)
                    return decision
                if event.event_type in {'FOLLOW','SUBSCRIPTION_EVENT'}:return self._batch(event,event.event_type)
                self.counts['registered_only']+=1;return FlowDecision('REGISTER_ONLY')
            value=normalized(event.text)
            repeat=bool(previous and normalized(previous)==value and now-previous_at<8)
            playful=bool(re.search(r'\b(sou um (batman|alien|dinossauro)|meu gato.*(prefeito|presidente)|personagem perdido|danco.*(robo|geladeira))\b',value))
            playful = playful or bool(re.search(r'\b(jarvis voce e doido|cade o esquilo|piada foi horrivel|piada ruim|seu maluco)\b',value))
            score=(35 if classification=='QUESTION' or '?' in event.text else 0)+(30 if presenter_answer else 0)+(25 if pending_question or classification=='FOLLOWUP' else 0)+(10 if not repeat else -40)
            if playful:score+=25
            if reaction_comment(event.text) and not presenter_answer and not playful:
                self.counts['registered_only']+=1;return FlowDecision('REGISTER_ONLY',score=5,reason='REACTION_ONLY')
            if current_intent(event.text)=='JOKE_REQUEST' and not playful:return FlowDecision('JOKE',2,60,author=author,created_at=now)
            if value in {'oi','ola','bom dia','boa tarde','boa noite','salve','oi jarvis'}:
                if repeat:self.counts['ignored']+=1;return FlowDecision('IGNORE',reason='SAME_AUTHOR_REPEAT_COOLDOWN')
                row.greeted=True
                return self._batch(event,'GREETING')
            if value in {'obrigado','obrigada','valeu'}:
                return FlowDecision('ACKNOWLEDGE',0,10,self._line((f'Valeu{", "+name if name else ""}!',f'Tamo junto{", "+name if name else ""}!')), (event.event_id,),author,created_at=now)
            if repeat:
                self.counts['ignored']+=1;return FlowDecision('IGNORE',score=score,reason='SAME_AUTHOR_REPEAT_COOLDOWN')
            if re.fullmatch(r'\d{1,3}',value) and not pending_question and not row.last_jarvis_reply:
                return FlowDecision('CURIOUS_FOLLOWUP',1,20,f'{value}? Essa eu não entendi. O que significa?',(event.event_id,),author,created_at=now)
            if playful:
                return FlowDecision('PLAY_ALONG',1,25,author=author,created_at=now)
            if re.search(r'\b(rodineles responde|pergunta pro rodineles|rodineles o que acha)\b',value):
                return FlowDecision('PASS_TO_HOST',1,60,'Rodineles, essa eu vou jogar pra você.',(event.event_id,),author,created_at=now)
            deep=bool(re.search(r'\b(explica em detalhes|explique em detalhes|aprofunda|passo a passo|fisica quantica)\b',value))
            action='DEEP_ANSWER' if deep else 'CONTINUE_THREAD' if pending_question or classification=='FOLLOWUP' or (row.last_jarvis_reply and value.startswith('e ')) else 'ANSWER' if score>=35 else 'COMMENT'
            level=4 if deep else 3 if action=='ANSWER' else 2
            if pace in {'BUSY','HYPER'} and not deep:level=min(level,2)
            return FlowDecision(action,level,score,author=author,created_at=now)

    def flush(self):
        with self.lock:
            now=self.clock();ready=[]
            for (kind,gift),b in list(self.batches.items()):
                if now-b['at']<self.batch_seconds:continue
                del self.batches[(kind,gift)];names=list(dict.fromkeys(n for n in b['authors'].values() if n))[:3]
                if now-b['at']>45:
                    self.counts['ignored']+=len(b['ids'])
                    self.logs.append('LIVE_FLOW | batch antigo descartado')
                    continue
                joined=', '.join(names) or 'pessoal'
                if kind=='GIFT':
                    quantity=f' ({b["quantity"]} no total)' if b['quantity_known'] else ''
                    gift_name=safe_name(gift) or 'presentes'
                    reply=self._line((f'{joined}, valeu por {gift_name}{quantity}!',f'Obrigado por {gift_name}{quantity}, {joined}!'))
                    action='GROUP_THANK';self.counts['gift_batches']+=1
                elif kind=='GREETING' or kind=='VIEWER_JOIN':
                    reply=self._line((f'Oi pra quem está chegando{": "+joined if names else ""}!',f'Sejam bem-vindos{", "+joined if names else ""}!',
                        f'Um salve{", "+joined if names else ""}! Bom ter vocês no papo.',f'Cheguem junto{", "+joined if names else ""}! Aqui cabe conversa leve.',
                        f'Bem-vindos ao papo{", "+joined if names else ""}. Fiquem à vontade!'));action='ACKNOWLEDGE'
                else:reply=self._line((f'Obrigado por acompanhar, {joined}!',f'Valeu por seguir esse papo, {joined}!'));action='THANK'
                if kind=='VIEWER_JOIN':self.counts['JOIN_GREETINGS_READY']+=len(b['ids'])
                ready.append(FlowDecision(action,1,50,reply,tuple(b['ids']),'public-batch',created_at=now,
                                          evidence=tuple(b['evidence']),reason='BATCH_READY',source_kind=kind))
            return ready

    def register_join_greeting(self,ident,count):
        with self.lock:
            pending=getattr(self,'_join_greeting_pending',None)
            if pending is None:self._join_greeting_pending=pending=OrderedDict()
            pending[ident]=max(0,int(count))
            while len(pending)>1000:pending.popitem(last=False)
            self.counts['JOIN_GREETINGS_QUEUED']+=max(0,int(count))

    def finish_join_greeting(self,ident,spoken):
        with self.lock:
            pending=getattr(self,'_join_greeting_pending',{})
            count=pending.pop(ident,0)
            if count:
                self.counts['JOIN_EVENTS_GREETED' if spoken else 'JOIN_GREETING_FAILURES']+=count

    def snapshot(self):
        with self.lock:
            return {key:self.counts[key] for key in (
                'JOIN_EVENTS_RECEIVED','JOIN_EVENTS_GROUPED','JOIN_GREETINGS_READY',
                'JOIN_GREETINGS_QUEUED','JOIN_EVENTS_GREETED','JOIN_GREETING_FAILURES','JOIN_DUPLICATES')}

    def delivered(self,author,text):
        with self.lock:
            row=self.viewers.get(author)
            if row:row.last_jarvis_reply=text[:200];row.recent_interactions.append((row.last_message,text[:200]));row.last_seen=self.clock()
            self.counts['spoken_responses']+=1
            self.recent.append((self.clock(),author,'SPOKEN_RESPONSE'))
            first=normalized(text).split()[:1]
            if first and first[0] in {'boa','valeu','oi','olha','entao','pessoal','obrigado'}:
                self.constructions.append(first[0])

    def writer_hint(self,decision):
        with self.lock:
            openings=[normalized(s).split()[0] for s in list(self.constructions)[-3:] if normalized(s).split()]
            openings=[s for s in openings if s in {'boa','valeu','oi','olha','entao','pessoal','obrigado'}]
            return decision.writer_hint()+(' Varie a abertura; evite repetir: '+json_quote(openings) if openings else '')

    def pass_to_host(self):
        with self.lock:self.wait_host_until=self.clock()+30

    def feedback_snapshot(self,since):
        with self.lock:
            rows=[r for r in self.feedback if since<=r[0] and self.clock()-r[0]<=30]
            n=len({r[1] for r in rows if r[1]})
            negative=any(r[5] in {'NEGATIVE_REACTION','MIXED_HUMOR'} or 'SAD_REACTION' in r[6] for r in rows)
            signal='NEUTRAL' if negative else 'STRONG_POSITIVE' if n>=5 else 'POSITIVE' if n>=3 else 'LOW_RESPONSE' if not rows and self.clock()-since>=30 else 'NEUTRAL'
            return {'CONTENT_RESPONSE':signal,'unique_authors':n,'messages':sum(r[2]=='CHAT_MESSAGE' for r in rows),
                'reactions':sum(r[3] for r in rows),'answers':sum(r[4] for r in rows),'events':sum(r[2]!='CHAT_MESSAGE' for r in rows)}

def json_quote(value):
    return __import__('json').dumps(value,ensure_ascii=False)
