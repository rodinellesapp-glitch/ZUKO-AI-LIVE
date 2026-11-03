"""Producer directions and bounded live state; no IO, devices or model access."""
import json
import re
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from live_entertainment import normalized

JARVIS_ROLE=('PRODUCER','WRITER','CO_HOST')


def current_intent(text):
    value=normalized(text)
    if re.search(r'\b(piadas?|humor)\b',value) and re.search(r'\b(cade|conta|conte|manda|quero|faz|faca|ruim|ruins)\b',value):return 'JOKE_REQUEST'
    if re.search(r'\b(agora|mudar|vamos|quero|assunto)\b.*\b(falar|conversar|sobre|assunto)\b',value):return 'TOPIC_SWITCH'
    return ''


@dataclass
class LiveProfile:
    theme: str='GENERAL_LIVE'
    objective: str='entreter e conversar'
    audience: str='público geral'
    tone: str='descontraído, divertido e espontâneo'
    estimated_duration: int=60
    conversion_goal: tuple=('CHAT','LIKE','FOLLOW','GIFT')
    presenter_name: str='Rodineles'
    jarvis_role: tuple=JARVIS_ROLE
    special_notes: str=''


@dataclass
class LivePlan:
    opening_hook: str='receber o público e apresentar o tema, sem inventar acontecimentos'
    possible_topics: list=field(default_factory=lambda:['cotidiano','histórias','humor','curiosidades'])
    stories: list=field(default_factory=lambda:['situação fictícia curta, claramente sinalizada'])
    humor_seeds: list=field(default_factory=lambda:['piada ruim do banco local','humor sobre ser um coapresentador virtual'])
    curiosity_seeds: list=field(default_factory=lambda:['detalhe curioso do tema, sem notícia atual não verificada'])
    engagement_ideas: list=field(default_factory=lambda:['escolha rápida','opinião pontual','reação coletiva'])
    possible_transitions: list=field(default_factory=lambda:['seguir desvio do chat','retomar tema após desvio'])
    cta_opportunities: list=field(default_factory=list)
    closing_direction: list=field(default_factory=lambda:['encerrar somente quando o apresentador indicar'])


@dataclass
class LiveState:
    current_topic: str='GENERAL_LIVE'
    previous_topic: str=''
    last_speaker: str=''
    last_audience_message: str=''
    last_jarvis_message: str=''
    recent_topics: deque=field(default_factory=lambda:deque(maxlen=32))
    recent_questions: deque=field(default_factory=lambda:deque(maxlen=30))
    recent_jokes: deque=field(default_factory=lambda:deque(maxlen=32))
    recent_reactions: deque=field(default_factory=lambda:deque(maxlen=40))
    recent_ctas: deque=field(default_factory=lambda:deque(maxlen=32))
    recent_events: deque=field(default_factory=lambda:deque(maxlen=40))
    audience_activity: int=0
    last_activity_at: float=0.
    audience_mood: str='QUIET'
    live_pace: str='QUIET'
    silence_duration: float=0
    rodineles_active: bool=False
    presenter_question_open: bool=False
    current_conversation_thread: str='GENERAL_LIVE'
    content_response: str='NEUTRAL'


class ContentPool:
    def __init__(self):self.items=OrderedDict();self.recent=deque(maxlen=32);self.cursors=OrderedDict()

    def seed(self,action,topic,now,excluded=()):
        for item in self.items.values():
            if now>=item['expires_at']:item['status']='EXPIRED'
        start=self.cursors.get((action,topic),0)
        for offset in range(128):
            variant=start+offset
            ident=f'{action}:{topic}:{variant}'
            if ident in self.recent or ident in excluded:continue
            item=self.items.get(ident)
            if item and item['status']=='USED':continue
            angles=('um contraste concreto do cotidiano','uma situação absurda imaginária','um detalhe prático pouco lembrado',
                    'uma escolha com consequências engraçadas','uma inversão inesperada','um exemplo simples com surpresa')
            item={'id':ident,'action':action,'topic':topic,'direction':f'{action} sobre {topic}: {angles[variant%len(angles)]}',
                  'status':'AVAILABLE','expires_at':now+600,'variant':variant}
            self.items[ident]=item;self.items.move_to_end(ident)
            while len(self.items)>64:self.items.popitem(last=False)
            return item
        return None

    def used(self,ident):
        if ident in self.items:
            item=self.items[ident];item['status']='USED'
            key=(item['action'],item['topic']);self.cursors[key]=item['variant']+1;self.cursors.move_to_end(key)
            while len(self.cursors)>64:self.cursors.popitem(last=False)
        self.recent.append(ident)


class LiveProducer:
    def __init__(self,clock):
        self.clock=clock;self.profile=LiveProfile();self.reset()

    def reset(self):
        self.state=LiveState(current_topic=self.profile.theme,current_conversation_thread=self.profile.theme)
        self.plan=LivePlan();self.pool=ContentPool();self.actions=deque(maxlen=30)
        self.logs=deque(maxlen=100);self.take_over=False;self.topic_at=0.;self.last_content_at=0.
        self.feedback_authors=set();self.feedback_negative=False;self.last_language_at=float('-inf')
        self.host_quiet_until=0.
        self.unanswered_actions=0
        self.question_serial=0
        self.pending_topic_action='START_TOPIC' if self.profile.theme!='GENERAL_LIVE' else ''
        self.plan.possible_topics=[self.profile.theme] if self.profile.theme!='GENERAL_LIVE' else ['cotidiano','histórias','humor','curiosidades']
        self.plan.cta_opportunities=list(self.profile.conversion_goal)
        self.logs.extend(('LIVE_PROFILE_LOADED','LIVE_PLAN_READY'))

    def configure(self,**values):
        allowed=set(LiveProfile.__dataclass_fields__)-{'jarvis_role'}
        if set(values)-allowed:raise ValueError('Campo de LiveProfile desconhecido')
        updates={}
        for key,value in values.items():
            if key=='conversion_goal':
                if isinstance(value,str):value=tuple(v.strip().upper() for v in value.split(','))
                if not set(value)<={'SUBSCRIBE','LIKE','FOLLOW','CHAT','GIFT','PRODUCT','NONE'}:raise ValueError('Conversão inválida')
            elif key=='estimated_duration':
                value=int(value)
                if not 1<=value<=1440:raise ValueError('Duração inválida')
            else:value=str(value).strip()[:200]
            updates[key]=value
        for key,value in updates.items():setattr(self.profile,key,value)
        self.profile.theme=self.profile.theme or 'GENERAL_LIVE';self.reset()

    def topic(self,topic,transition=None):
        if not topic:return
        topic=topic[:80]
        if topic!=self.state.current_topic:
            self.pending_topic_action=transition or ('START_TOPIC' if self.state.current_topic=='GENERAL_LIVE' else 'CHANGE_TOPIC')
            self.state.previous_topic=self.state.current_topic;self.state.recent_topics.append(topic)
            self.state.current_topic=topic;self.state.current_conversation_thread=topic
        self.topic_at=self.clock()

    def audience(self,author,text,reaction=None):
        self.unanswered_actions=0
        self.state.last_speaker='AUDIENCE';self.state.audience_activity+=1
        self.state.last_activity_at=self.clock()
        self.state.last_audience_message=re.sub(r'\b\d{5,}\b|\S+@\S+','[omitido]',text[:160])
        if self.last_content_at and self.clock()-self.last_content_at<=30:
            positive=reaction and reaction.get('emoji_count') and set(reaction['categories']) & {'LAUGH','LOVE','LIKE','APPLAUSE','HYPE','FLOWER','CELEBRATION','STRONG_APPROVAL'}
            if positive and len(self.feedback_authors)<200:self.feedback_authors.add(author)
            if reaction and reaction.get('text_intent') in {'NEGATIVE_REACTION','MIXED_HUMOR'}:self.feedback_negative=True
            n=len(self.feedback_authors)
            signal='NEUTRAL' if self.feedback_negative else 'STRONG_POSITIVE' if n>=5 else 'POSITIVE' if n>=3 else 'NEUTRAL'
            if signal!=self.state.content_response:self.state.content_response=signal;self.logs.append('CONTENT_RESPONSE | '+signal)

    def human(self,text='',control=None):
        self.state.last_speaker=self.profile.presenter_name;self.state.rodineles_active=True
        self.state.last_activity_at=self.clock()
        if control=='TAKE_OVER':self.take_over=True;self.state.rodineles_active=False
        if control=='RETURN_CONTROL':self.take_over=False;self.host_quiet_until=self.clock()+45
        self.state.current_conversation_thread='HOST' if not self.take_over else self.state.current_topic

    def decide(self,choice,now,topic=None,excluded=()):
        if self.last_content_at and now-self.last_content_at>30 and not self.feedback_authors and self.state.content_response!='LOW_RESPONSE':
            self.state.content_response='LOW_RESPONSE';self.logs.append('CONTENT_RESPONSE | LOW_RESPONSE')
        if topic and topic!=self.state.current_topic:self.topic(topic)
        if self.state.current_topic!=self.profile.theme and now-self.topic_at>=600:self.topic(self.profile.theme,'RETURN_TOPIC')
        live_topic=self.state.current_topic
        invites=choice.category in {'PERGUNTA_DIVERTIDA','OPINIAO_AUDIENCIA','DESAFIO_CHAT','JOGO_RAPIDO','CTA_CHAT'}
        recent=list(self.actions)
        if recent and recent[-1]['invites']:invites=False
        if sum(a['invites'] for a in recent)>=max(1,(len(recent)+1)*.30):invites=False
        if self.state.live_pace in {'BUSY','HYPER'}:invites=False
        if self.state.content_response=='LOW_RESPONSE':invites=False
        mapping={'HUMOR':'TELL_JOKE','CURIOSIDADE':'SHARE_CURIOSITY','HISTORIA_LEVE':'TELL_STORY',
                 'JARVIS_PROJECT':'TALK_TO_RODINELES','JOGO_RAPIDO':'RUN_QUICK_GAME','CTA_CHAT':'MAKE_CTA',
                 'CTA_LIKE':'MAKE_CTA','CTA_FOLLOW':'MAKE_CTA','CTA_GIFT':'MAKE_CTA'}
        action=mapping.get(choice.category,'ASK_AUDIENCE' if invites else 'MAKE_COMMENT')
        if choice.category=='JOGO_RAPIDO' and not invites:action='MAKE_COMMENT'
        if choice.category=='HUMOR':invites=False
        if action=='MAKE_COMMENT':
            action=self.pending_topic_action or ('FILL_SILENCE' if choice.category=='COTIDIANO' else 'CONTINUE_TOPIC' if live_topic!='GENERAL_LIVE' else 'MAKE_COMMENT')
        seed=self.pool.seed(action,live_topic,now,excluded)
        if not seed:return None
        # Decisions and grounding are code-owned; the model may only phrase speech.
        data={'action':action,'topic':live_topic,'invites':invites,'seed':dict(seed),'idea':choice.category}
        if len(self.pool.items)==1 and not self.actions:self.logs.append('CONTENT_POOL_REFILL')
        return data

    def render(self,data,choice):
        action,topic,v=data['action'],data['topic'],data['seed']['variant']
        label=topic if topic!='GENERAL_LIVE' else ('café','games','segunda-feira','controle remoto','despertador','pizza','cinema','fila do mercado')[v%8]
        if action=='TELL_JOKE':
            prefix=f'No universo de {label}, até o humor derrapa. ' if topic!='GENERAL_LIVE' else ''
            return prefix+choice.text.split(' Essa veio do banco')[0]
        if action=='MAKE_CTA':
            goal=choice.category.removeprefix('CTA_')
            if goal=='FOLLOW' and 'SUBSCRIBE' in self.profile.conversion_goal:goal='SUBSCRIBE'
            if goal=='CHAT' and 'PRODUCT' in self.profile.conversion_goal:goal='PRODUCT'
            if goal not in self.profile.conversion_goal or 'NONE' in self.profile.conversion_goal:return self.comment(label,v)
            lines={'LIKE':'Curtiu? Deixa um like!', 'FOLLOW':'Segue o canal pra acompanhar as próximas.',
                   'GIFT':'Se quiser apoiar com um presente, valeu demais!',
                   'CHAT':f'Qual é a sua opinião sobre {label}?',
                   'SUBSCRIBE':'Se inscreve pra acompanhar as próximas!',
                   'PRODUCT':'Rodineles pode explicar os detalhes do produto.'}
            prefixes=('', 'Se estiver curtindo: ', 'Fica o convite: ', 'Gostou? ')
            return prefixes[v%4]+lines.get(goal,lines['CHAT'])
        if action=='TALK_TO_RODINELES':
            return (f'Rodineles, qual é a sua sobre {label}?',f'Rodineles, essa é sua: {label}.',f'E você, Rodineles, também curte {label}?')[v%3]
        if data['invites']:
            q=self.question_serial
            if topic=='GENERAL_LIVE':label=('café','games','segunda-feira','controle remoto','despertador','pizza','cinema','fila do mercado')[q%8]
            return (f'Sobre {label}: você prefere praticidade ou novidade?',
                    f'Se {label} virasse filme, seria comédia ou aventura?',
                    f'Qual seria o superpoder mais inútil ligado a {label}?',
                    f'Um título de filme para {label}: qual seria o seu?')[(q//8)%4 if topic=='GENERAL_LIVE' else q%4]
        if action=='TELL_STORY':
            return (f'Imagina uma competição de {label}: o troféu chega atrasado porque pegou a fila errada.',
                    f'Cena fictícia: um esquilo assume o departamento de {label}. A primeira regra é pagar tudo em castanhas.',
                    f'Imagina um detetive investigando {label}. A pista principal estava no bolso dele o tempo todo.')[v%3]
        if action=='SHARE_CURIOSITY':
            return (f'Pensando em {label}: quanto mais opções, mais difícil escolher. Até escolher pizza vira reunião.',
                    f'O assunto de {label} tem um rival poderoso: o botão de adiar do despertador.',
                    f'Pensar em {label} combina com aquela ideia que parece ótima às duas da manhã e estranha no dia seguinte.')[v%3]
        return self.comment(label,v)

    @staticmethod
    def comment(label,v):
        subjects=('um manual de instruções','um botão de desfazer','uma trilha sonora','um modo férias',
                  'um controle remoto','um alarme educado','um calendário de folga','um placar imaginário')
        endings=('Eu apertaria primeiro e leria as instruções depois.',
                 'A versão de bolso já teria fila de espera.',
                 'Imagina explicar isso numa entrevista de emprego.',
                 'O tutorial precisaria de outro tutorial.')
        openings=(f'Se {label} tivesse {subjects[v%8]}, a vida ganharia uma expansão.',
                  f'Inventei {subjects[v%8]} para {label}. Patente imaginária pendente.',
                  f'A ideia de {label} com {subjects[v%8]} seria um lançamento improvável.',
                  f'Na versão alternativa de {label}, até o esquilo usa {subjects[v%8]}.')
        return openings[(v//32)%4]+' '+endings[(v//8)%4]

    def delivered(self,data,text):
        self.unanswered_actions=self.unanswered_actions+1 if not self.feedback_authors else 0
        if data['invites']:self.question_serial+=1
        self.actions.append({'action':data['action'],'invites':data['invites'],'topic':data['topic']})
        self.pool.used(data['seed']['id']);self.logs.append('CONTENT_POOL_USED')
        self.logs.append('RECENT_AUTONOMOUS_ACTIONS | '+','.join(a['action'] for a in list(self.actions)[-8:]))
        self.state.last_speaker='JARVIS';self.state.last_jarvis_message=text[:200]
        if data['action'] in {'START_TOPIC','CHANGE_TOPIC','RETURN_TOPIC'}:self.pending_topic_action=''
        if data['invites']:self.state.recent_questions.append(text[:200])
        if data['action']=='TELL_JOKE':self.state.recent_jokes.append(data['seed']['id'])
        if data['action']=='MAKE_CTA':self.state.recent_ctas.append(self.clock())
        if data['action']=='TALK_TO_RODINELES':self.host_quiet_until=self.clock()+30
        self.last_content_at=self.clock();self.feedback_authors.clear();self.feedback_negative=False;self.state.content_response='NEUTRAL'

    def language_input(self,data):
        return json.dumps({'ROLE':JARVIS_ROLE,'LIVE_PROFILE':vars(self.profile),'LIVE_STATE':{
            'current_topic':self.state.current_topic,'audience_mood':self.state.audience_mood,
            'rodineles_active':self.state.rodineles_active,'content_response':self.state.content_response},
            'ACTION':data['action'],'SEED':data['seed']['direction'],'LENGTH_LIMIT':'1–3 frases, 20–60 palavras',
            'INVITE_AUDIENCE':data['invites'],'GROUNDING':'Não invente clima, localização, ações do apresentador, espectadores, eventos ou reações. Sem Tools. História fictícia deve ser indicada.'},ensure_ascii=False)

    def language_due(self,data):
        return bool(data and data['action']=='TELL_STORY' and self.clock()-self.last_language_at>=180)

    def spoken_language(self,text,data,fallback):
        """Conservative local guard, in addition to the model's output guard."""
        value=normalized(text)
        forbidden=r'\b(chovendo|ensolarado|aqui em|hoje em|rodineles esta|rodineles acabou|recebemos presentes|ganhamos presentes|eu comi|eu viajei|eu dirigi|execute|executar|powershell|firestore|access token)\b'
        if not text or len(text.split())>70 or re.search(forbidden,value):return fallback
        if not data['invites'] and '?' in text:return fallback
        if data['action']=='TELL_STORY' and not re.search(r'\b(fictici[ao]|inventad[ao]|imagina|imagine)\b',value):return fallback
        return text

    def drain_logs(self):
        result=list(self.logs);self.logs.clear();return result
