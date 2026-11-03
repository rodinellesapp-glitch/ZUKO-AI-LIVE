"""Versioned prompt, deterministic programme plans and optional output adapter.

No network, device ownership, viewer identifiers or executable model actions.
"""
from collections import Counter, deque
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
import json
import math
import re
from zuko_conversation import normalized, private_safe

HERE = Path(__file__).resolve().parent
FRAMES = ('RESENHA DO DIA', 'VIDA ADULTA', 'HISTÓRIAS DO COTIDIANO',
          'ZUKO EXPLICA', 'DESAFIO ZUKO', 'VOCÊ SABIA?', 'HUMOR TECH',
          'BATALHA DAS TECNOLOGIAS', 'INDÚSTRIA DO FUTURO', 'PERGUNTA MALUCA',
          'BASTIDORES DO ZUKO', 'ZUKO IMPROVISA')
TOPICS = ('trabalho_e_correria', 'supermercado_e_economia', 'familia_e_domingo',
          'transporte_e_transito', 'grupos_de_whatsapp', 'vida_adulta',
          'costumes_e_geracoes', 'gambiarras_criativas',
          'inteligencia_artificial', 'manutencao_industrial', 'sensores_e_caldeiras',
          'robotica', 'energia', 'programacao', 'tecnologia_cotidiana', 'seguranca_digital')
INTENTS = frozenset(('opening', 'explain', 'challenge', 'question', 'answer_self',
                     'transition', 'resume', 'humor', 'closing', 'greeting',
                     'gratitude', 'support', 'affirmation', 'disagreement',
                     'celebration', 'comment', 'story'))
EMOTIONS = frozenset(('calm', 'joy', 'surprise', 'gratitude', 'empathy'))
EMOTION_ALIASES = {'neutral':'calm', 'happy':'joy', 'excited':'joy',
                   'curious':'calm', 'surprised':'surprise', 'amused':'joy',
                   'empathetic':'empathy', 'thankful':'gratitude'}
SPEECH_ANIMATIONS = frozenset(('Idle', 'Wave', 'Yes', 'No', 'Jump'))
ACTIONS = frozenset(('continue', 'wait_for_response', 'transition', 'close'))
STATES = frozenset(('ABERTURA', 'APRESENTANDO', 'INTERAGINDO', 'DESAFIANDO',
                    'AGUARDANDO_RESPOSTA', 'IMPROVISANDO', 'REFLETINDO', 'PAUSADO', 'ENCERRANDO'))


@lru_cache(maxsize=1)
def prompt_library():
    data = json.loads((HERE / 'zuko_v3_prompt.json').read_text(encoding='utf-8'))
    if not isinstance(data.get('system'), str) or not data.get('version'):
        raise ValueError('V3_PROMPT_INVALID')
    return data


def build_system_prompt(personality, autonomous=False, *, structured=False):
    data = prompt_library()
    examples = '\n'.join('Situação: '+row['situation']+'\nFala ilustrativa: '+row['speech']
                         for row in data['examples'])
    common = ('Converse como streamer brasileiro numa resenha entre amigos, nunca como telejornal, aula ou atendimento. '
              'Responda primeiro ao sentido real da mensagem; mencionar o nome não substitui responder ao conteúdo. '
              'Conecte comentários de pessoas diferentes somente quando o histórico mostrar uma relação clara. '
              'Use humor criativo ligado ao assunto, sem ridicularizar quem comentou; varie ritmo e energia, evite bordões, '
              'frases genéricas e motivação automática. Pergunte só quando a resposta puder fazer a conversa avançar. '
              'Comentários reais parecidos continuam sendo interações válidas: responda ao que há de novo sem tratar '
              'semelhança como duplicata. A proteção contra repetição semântica vale para falas autônomas. '
              'Em assuntos delicados, acolha com clareza e deixe o humor de lado. Nunca invente participantes, comentários, '
              'presentes, vínculos entre espectadores ou experiências pessoais reais. História inventada deve soar '
              'explicitamente imaginada. A fala final deve soar natural em voz alta; não inclua instruções de animação nela. ')
    task = (common+'Siga o plano público do programa e desenvolva uma ideia nova. Se operator_topic estiver preenchido, ele é o tema ativo obrigatório: '
            'mantenha todas as falas autônomas nesse tema até o operador alterá-lo. Varie ângulos e subtemas dentro dele; não o substitua por temas internos. '
            'Apresente cada fala como conversa com quem está acompanhando: explique a ideia diretamente ao público, use "vocês" ou "você" quando soar natural '
            'e conecte o tema a situações cotidianas sem fingir conhecer os espectadores. Varie entre curiosidade, humor leve, opinião e convite à conversa; '
            'faça uma pergunta aberta ou convite ao chat em algumas falas, não em todas, não repita "galera" como bordão e respeite asked_questions. '
            'Só use nomes, contagens ou participação quando esses dados estiverem explicitamente disponíveis em audience_activity. '
            'Desenvolva subtopic antes de avançar para next_idea. Sem tema do operador, use a programação interna e transicione após até três falas do mesmo tema. '
            'Compare o significado das últimas falas, não só as palavras: não repita a mesma observação com sinônimos. '
            'Se uma ideia já apareceu, avance para um ângulo realmente diferente ou transicione sem anunciar a regra. '
            'asked_questions contém perguntas já feitas: não as repita. Retome story_anchors e resume_points '
            'somente quando fornecidos e pertinentes. audience_activity contém apenas sinais observados, '
            'sem inventar participação quando faltarem dados. No silêncio, se a autonomia estiver ativa, faça uma '
            'intervenção curta, deixe pausas naturais e espere; não fale para preencher cada intervalo. Comentários novos '
            'têm prioridade sobre o monólogo; retome o tema anterior depois somente se houver um gancho claro.'
            if autonomous else common+'Priorize responder ao comentário real e ao seu contexto individual. Use o histórico '
            'recente para continuar uma conversa ou relacionar comentários, sem misturar histórias de espectadores. '
            'Se a mensagem repetir algo já dito, trate a nova mensagem com atenção e acrescente uma resposta útil, '
            'sem simplesmente repetir sua fala anterior.')
    output = ('Retorne JSON compacto com speech, emotion, animation, intent, topic e reply_to. '
              'speech contém apenas a fala; associe emotion e intent ao conteúdo final; emotion usa NEUTRAL, HAPPY, EXCITED, CURIOUS, '
              'SURPRISED, AMUSED, EMPATHETIC ou THANKFUL. animation é só sugestão: '
              'Idle, Wave, Yes, No ou Jump; a seleção local preserva prioridades e limites. '
              'intent usa greeting, comment, question, humor, support, gratitude, celebration, '
              'affirmation, disagreement, story ou a intenção do plano. topic é o identificador '
              'do plano ou um assunto curto em snake_case. Copie reply_to dos dados do sistema '
              'para comentários; use null quando ausente. Não crie outros campos.'
              if structured else
              'Retorne somente a fala final, sem JSON, análise, markdown ou emojis. '
              'Ações entre colchetes, caso presentes, são metadados descartáveis; nunca falas.')
    return ('PROMPT_VERSION='+data['version']+'\n'+personality.get('style', '')+'\n'+
            personality.get('instruction', '')+'\n'+data['system']+'\n'+task+'\n'+output+
            '\n<exemplos_ilustrativos>\n'+examples+'\n</exemplos_ilustrativos>')


def speech_only(text):
    """Acting cues are metadata, including cues in the middle of a sentence."""
    return re.sub(r'\s+', ' ', re.sub(r'\[[^\]\r\n]*\]', ' ', str(text or ''))).strip()


def salvage_audience_speech(raw):
    """Extract only a complete JSON-escaped speech string from a broken audience envelope."""
    if not isinstance(raw,str) or len(raw)>8000:return None
    match=re.search(r'"speech"\s*:\s*"((?:\\.|[^"\\])*)"',raw)
    if not match:return None
    try:value=json.loads('"'+match.group(1)+'"')
    except (ValueError,TypeError):return None
    return value if isinstance(value,str) and value.strip() and len(value)<=600 else None


def load_config():
    data = json.loads((HERE / 'zuko_v3_config.json').read_text(encoding='utf-8'))
    if data.get('version') != 3 or data.get('enabled_on_start') is not False:
        raise ValueError('V3_CONFIG_INVALID')
    if data.get('default_mode') not in ('CALMO', 'NORMAL', 'ALTA ENERGIA'):
        raise ValueError('V3_MODE_INVALID')
    for mode in ('CALMO', 'NORMAL', 'ALTA ENERGIA'):
        row = data['modes'][mode]
        if not 10 <= row['interval'] <= 300 or not 2 <= row['wait'] <= 30:
            raise ValueError('V3_CADENCE_INVALID')
        if not 2 <= row['challenge_every'] <= 20 or row['gesture_intensity'] not in (0, 1, 2):
            raise ValueError('V3_MODE_INVALID')
    limits=data['limits']
    bounds={'autonomous_gemini_per_session':(1,100), 'autonomous_gemini_per_minute':(1,4),
            'audience_reserve_calls':(0,100), 'failure_threshold':(1,10),
            'circuit_seconds':(10,600), 'failure_backoff_seconds':(2,120),
            'pending_ttl_seconds':(10,120)}
    for key,(minimum,maximum) in bounds.items():
        if type(limits.get(key)) is not int or not minimum <= limits[key] <= maximum:
            raise ValueError('V3_LIMIT_INVALID:'+key)
    reflection=data['reflection']
    if (type(reflection.get('every_completed')) is not int or not 3<=reflection['every_completed']<=100 or
        type(reflection.get('max_per_session')) is not int or not 0<=reflection['max_per_session']<=5 or
        type(reflection.get('use_gemini')) is not bool):raise ValueError('V3_REFLECTION_LIMIT_INVALID')
    for key in ('input_per_million','output_per_million'):
        rate=data['cost'].get(key)
        if rate is not None and (type(rate) not in (int,float) or not math.isfinite(rate) or not 0<=rate<=10000):
            raise ValueError('V3_COST_RATE_INVALID')
    return data


@dataclass(frozen=True)
class ContentPlan:
    frame: str
    topic: str
    state: str
    intent: str
    emotion: str
    objective: str
    next_action: str = 'continue'
    pause_seconds: int = 8
    gesture_intensity: int = 1
    question: str = ''
    prompt_version: str = 'zuko-presenter-3.1.0'
    subtopic: str = ''
    next_idea: str = ''
    operator_topic: str = ''
    asked_questions: tuple = ()
    story_anchors: tuple = ()
    resume_points: tuple = ()
    planning_reason: str = ''

    def context(self):
        return asdict(self)


class ContentPlanner:
    def __init__(self):
        self.completed = 0
        self.frame = ''
        self.topic = ''
        self.step = 0
        self.frames = deque(maxlen=4)
        self.frame_uses = Counter()
        self.topics = deque(maxlen=3)
        self.pending_question = None
        self.resume = False
        self.operator_topic = ''
        self.topic_change_requested = False
        self.forced_transition = False
        self.forced_topic = ''
        self.questions = deque(maxlen=8)
        self.stories = deque(maxlen=3)
        self.resume_points = deque(maxlen=4)

    def suggest_topic(self, topic):
        if not isinstance(topic,str) or len(topic)>160:
            raise ValueError('V4_TOPIC_INVALID')
        safe=private_safe(topic).strip()[:120]
        if safe!=self.operator_topic:
            self.operator_topic=safe
            self.topic_change_requested=True

    def force_transition(self, topic=''):
        """Request a new programme topic after an autonomous semantic repeat."""
        self.forced_transition=True
        if isinstance(topic,str):self.forced_topic=topic[:64]

    @staticmethod
    def question_parts(speech):
        return [part.strip()+'?' for part in re.findall(r'([^.!?]+)\?',speech) if part.strip()][:3]

    def repeated_question(self, speech):
        previous={normalized(question) for question in self.questions}
        return any(normalized(question) in previous for question in self.question_parts(speech))

    def _with_context(self, plan):
        angles=('uma situação concreta','um erro comum e como evitá-lo','um detalhe inesperado',
                'um ponto de vista diferente','uma comparação leve','uma pergunta que abra outro ângulo')
        step=self.completed%len(angles)
        reason=('retomada do tema após comentário' if self.resume else
                'tema personalizado aplicado pelo operador' if self.topic_change_requested and self.operator_topic else
                'variação por repetição, mantendo o tema personalizado' if self.forced_transition and self.operator_topic else
                'continuidade do tema personalizado' if self.operator_topic else
                'transição de variedade interna' if self.forced_transition else
                'novo quadro da programação' if plan.topic!=self.topic else 'continuidade do subtema')
        return replace(plan,subtopic=angles[step],next_idea=angles[(step+1)%len(angles)],
            operator_topic=self.operator_topic,asked_questions=tuple(self.questions)[-4:],
            story_anchors=tuple(self.stories),resume_points=tuple(self.resume_points),planning_reason=reason)

    def propose(self, mode, now, weights=None):
        if self.pending_question and not self.topic_change_requested:
            if now < self.pending_question['until']:
                return None
            return self._with_context(ContentPlan(self.frame,self.topic,'IMPROVISANDO','answer_self','calm',
                'Responda à sua própria pergunta com explicação nova, sem inventar participação.',
                'transition',mode['wait'],mode['gesture_intensity'],self.pending_question['speech']))
        if self.resume and self.topic and not self.topic_change_requested:
            return self._with_context(ContentPlan(self.frame,self.topic,'APRESENTANDO','resume','calm',
                'Retome o ponto do programa após responder ao comentário real; avance um detalhe.',
                pause_seconds=mode['wait'],gesture_intensity=mode['gesture_intensity']))
        change = not self.topic or self.step >= 3 or self.topic_change_requested or self.forced_transition
        weights=weights or {}
        if change:
            eligible=[frame for frame in FRAMES if frame not in self.frames]
            frame=max(eligible,key=lambda value:(weights.get(value,1.0)/(1+self.frame_uses[value]),-FRAMES.index(value)))
            excluded=set(self.topics)
            if self.forced_transition and self.forced_topic:excluded.add(self.forced_topic)
            candidates=[topic for topic in TOPICS if topic not in excluded]
            topic='tema_personalizado' if self.operator_topic else candidates[(self.completed//3) % len(candidates)]
        else:
            frame,topic=self.frame,self.topic
        challenge = self.completed > 0 and (self.completed % mode['challenge_every']==0 or frame=='DESAFIO ZUKO')
        intent = ('opening' if self.completed==0 else 'challenge' if challenge else
                  'story' if frame=='HISTÓRIAS DO COTIDIANO' and change else
                  'humor' if frame=='HUMOR TECH' else 'transition' if change else 'explain')
        objective = {'opening':'Abra uma resenha do cotidiano brasileiro com uma observação concreta e curiosa, sem inventar público.',
                     'challenge':'Proponha um desafio compreensível; dê espaço para resposta sem pressionar.',
                     'humor':'Crie humor original ligado ao tema e acrescente uma observação útil.',
                     'story':'Desenvolva uma situação imaginada curta, explicitamente fictícia, ligada ao tema; deixe um ponto para retomar.',
                     'transition':'Faça uma transição natural e apresente um ângulo novo do tema.',
                     'explain':'Desenvolva um ponto novo do mesmo tema, com exemplo simples e sem repetir a última fala.'}[intent]
        return self._with_context(ContentPlan(frame,topic,'ABERTURA' if intent=='opening' else 'DESAFIANDO' if challenge else 'APRESENTANDO',
            intent,'joy' if mode['gesture_intensity']>0 else 'calm',objective,
            'wait_for_response' if challenge else 'continue',mode['wait'],mode['gesture_intensity']))

    def delivered(self, plan, speech, now, pause=None):
        changed=plan.frame!=self.frame or plan.topic!=self.topic
        self.frame,self.topic=plan.frame,plan.topic
        if changed:
            self.frames.append(plan.frame);self.topics.append(plan.topic);self.step=0
            self.frame_uses[plan.frame]+=1
            self.forced_transition=False;self.forced_topic=''
        self.completed+=1;self.step+=1;self.resume=False
        if plan.operator_topic==self.operator_topic:
            if self.topic_change_requested:self.pending_question=None
            self.topic_change_requested=False
        for question in self.question_parts(speech):self.questions.append(question[:180])
        if plan.intent=='story':self.stories.append({'topic':plan.topic,'anchor':private_safe(speech)[:160]})
        self.resume_points.append({'topic':plan.topic,'subtopic':plan.subtopic})
        if plan.intent=='answer_self':
            self.pending_question=None;self.step=3
        elif plan.next_action=='wait_for_response':
            self.pending_question={'speech':speech[:600],'until':now+(pause if pause is not None else plan.pause_seconds)}

    def audience_reply_delivered(self):
        if self.topic:self.resume=True
        self.pending_question=None


def decode_generation(raw, plan=None):
    """Plain speech stays compatible; JSON-looking output must pass the schema."""
    if not isinstance(raw,str) or not raw.strip() or len(raw)>8000:
        raise ValueError('V3_OUTPUT_INVALID')
    text=raw.strip()
    if text.startswith('```'):
        match=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',text,re.S|re.I)
        if not match:raise ValueError('V3_JSON_INVALID')
        text=match.group(1)
    defaults=plan.context() if isinstance(plan,ContentPlan) else dict(plan or {})
    if re.match(r'^\[[A-Za-zÀ-ÖØ-öø-ÿ]',text):
        text=speech_only(text)
    if text.startswith(('{','[')):
        try:data=json.loads(text)
        except (ValueError,TypeError) as error:raise ValueError('V3_JSON_INVALID') from error
        allowed={'speech','intent','emotion','topic','next_action','suggested_pause_seconds','memory_tags',
                 'animation','reply_to'}
        if not isinstance(data,dict) or set(data)-allowed or not isinstance(data.get('speech'),str):
            raise ValueError('V3_SCHEMA_INVALID')
        if any(key in data and not isinstance(data[key],str) for key in ('intent','emotion','topic','next_action')):
            raise ValueError('V3_ENUM_TYPE_INVALID')
        if data.get('intent',defaults.get('intent','explain')) not in INTENTS:
            raise ValueError('V3_INTENT_INVALID')
        emotion=data.get('emotion',defaults.get('emotion','calm')).casefold()
        emotion=EMOTION_ALIASES.get(emotion,emotion)
        if emotion not in EMOTIONS:
            raise ValueError('V3_EMOTION_INVALID')
        if 'emotion' in data:data['emotion']=emotion
        topic=data.get('topic',defaults.get('topic',TOPICS[0]))
        if topic not in TOPICS and not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',topic):
            raise ValueError('V3_TOPIC_INVALID')
        if 'animation' in data and (not isinstance(data['animation'],str) or data['animation'] not in SPEECH_ANIMATIONS):
            raise ValueError('V3_ANIMATION_INVALID')
        reply_to=data.get('reply_to')
        if reply_to is not None and (not isinstance(reply_to,str) or not re.fullmatch(r'[\w:./-]{1,128}',reply_to)):
            raise ValueError('V3_REPLY_INVALID')
        if data.get('next_action',defaults.get('next_action','continue')) not in ACTIONS:
            raise ValueError('V3_ACTION_INVALID')
        pause=data.get('suggested_pause_seconds',defaults.get('pause_seconds',8))
        if type(pause) not in (int,float) or not math.isfinite(pause) or not 2<=pause<=30:
            raise ValueError('V3_PAUSE_INVALID')
        tags=data.get('memory_tags',[])
        if not isinstance(tags,list) or len(tags)>5 or any(not isinstance(t,str) or not re.fullmatch(r'[a-z0-9_]{1,32}',t) for t in tags):
            raise ValueError('V3_TAG_INVALID')
    else:
        data={'speech':text}
    speech=speech_only(data['speech'])
    if not speech or len(speech)>600 or speech.startswith(('{','[')) or '```' in speech:
        raise ValueError('V3_SPEECH_INVALID')
    return speech,{key:value for key,value in data.items() if key!='speech'}
