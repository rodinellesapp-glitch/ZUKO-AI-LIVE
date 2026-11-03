"""Bounded RAM-only interpretation of replies to an actually spoken question."""
import re
import time
from collections import Counter, OrderedDict
from threading import RLock
from live_entertainment import normalized
from live_reactions import categories, reaction_only
from live_cohost import current_intent


class PresenterQuestionWindow:
    def __init__(self,clock=time.monotonic,seconds=25):
        self.clock,self.seconds=clock,seconds;self.lock=RLock();self.reset()

    def reset(self):
        with self.lock:self.current=None;self.last_opened_id=None

    def open(self,event_id,text):
        with self.lock:
            if event_id==self.last_opened_id:return
            value=normalized(text)
            if '?' not in text and not re.search(r'\b(descrev|descreva|descrevam|manda|mandem|complete|escolham)\b',value):return
            groups=(('celular',('celular',)),('computador',('computador','pc')))
            pairs=(groups,(('café',('cafe',)),('chá',('cha',)),('energético',('energetico',))),
                (('vendo',('vendo','assistindo')),('fazendo',('fazendo','pratica','mao na massa')),('os dois',('os dois','ambos'))),
                (('piada',('piada','humor')),('pergunta',('pergunta','curiosidade'))))
            choices={}
            for pair in pairs:
                hits=sum(any(alias in value for alias in aliases) for _,aliases in pair)
                if hits>=2:choices={label:aliases for label,aliases in pair};break
            expected='A_OR_B' if len(choices)==2 else 'SHORT_CHOICE' if choices else 'FREE_TEXT'
            if categories(text):expected='EMOJI'
            elif 'verdadeiro ou falso' in value:
                expected='YES_NO';choices={'verdadeiro':('verdadeiro','sim'),'falso':('falso','nao')}
            elif re.search(r'\b(sim ou nao|concordam|voce concorda)\b',value):
                expected='YES_NO';choices={'sim':('sim','concordo'),'não':('nao','discordo')}
            elif re.search(r'\b(desafio|descreva|descrevam|complete|tres palavras)\b',value):expected='CHALLENGE_RESPONSE'
            now=self.clock();self.last_opened_id=event_id
            self.current={'question_id':event_id,'question_text':text[:400],
                'expected_response_type':expected,'opened_at':now,'expires_at':now+self.seconds,
                'responses':OrderedDict(),'authors':OrderedDict(),'seen':set(),'choices':choices,
                'expected_emojis':tuple(categories(text))}

    def match(self,text):
        with self.lock:
            q=self.current
            if not q or self.clock()>=q['expires_at']:return None
            if current_intent(text)=='JOKE_REQUEST':return None
            value=normalized(text)
            if (len(text)>160 or len(value.split())>15 or '?' in text or re.search(r'https?://',text)
                    or value in {'oi','ola','bom dia','boa tarde','boa noite','salve','obrigado','valeu'}
                    or re.match(r'^(jarvis |qual |como |por que |porque |onde |quando |me explica|me ajuda|explique|recomenda|execute |abra |pausar |parar )',value)):return None
            expected=q['expected_response_type'];answer=None
            if expected=='EMOJI':
                if reaction_only(text) and set(categories(text)) & set(q['expected_emojis']):answer='EMOJI'
            elif q['choices']:
                for label,aliases in q['choices'].items():
                    if any(re.search(r'\b'+re.escape(alias)+r'\b',value) for alias in aliases):answer=label;break
            elif value and not reaction_only(text):answer=text.strip()[:120]
            if answer is None:return None
            return {'question_id':q['question_id'],'question_text':q['question_text'],
                'expected_response_type':expected,'answer':answer,'emoji':expected=='EMOJI'}

    def accept(self,message_id,author,text):
        with self.lock:
            context=self.match(text)
            if not context:return None
            q=self.current
            if message_id in q['seen'] or len(q['seen'])>=200:return None
            q['seen'].add(message_id);q['responses'][message_id]=context['answer']
            q['authors'][author]=context['answer']
            context['responses']=len(q['responses']);context['unique_authors']=len(q['authors'])
            votes=Counter(q['authors'].values())
            if context['unique_authors']>=3:
                top,count=votes.most_common(1)[0]
                # A majority claim requires distinct author votes, never repeated messages.
                if q['choices'] and count>len(q['authors'])/2:
                    reply=f'{top.capitalize()} está aparecendo bastante por aqui: {count} de {len(q["authors"])} participantes escolheram essa opção. Bora continuar nesse assunto!'
                else:reply='Boa, o chat entrou na conversa! Vi respostas diferentes para essa pergunta. Vamos aproveitar as ideias e continuar por aí.'
            elif context['answer']=='computador':reply='Computador? Aí eu entendo: tela maior e espaço para trabalhar contam bastante nessa escolha.'
            elif context['answer']=='celular':reply='Celular tem essa vantagem de acompanhar a gente. Praticidade é um bom ponto para esse lado da conversa.'
            elif context['answer'] in {'café','chá','energético'}:reply=f'Time {context["answer"]} marcou presença! Boa escolha para puxar esse papo de hábitos do dia a dia.'
            elif context['answer'] in {'vendo','fazendo','os dois'}:reply='Boa! Ver um exemplo e testar na prática pode render uma conversa interessante. Que assunto você gostaria de aprender desse jeito?'
            elif 'lavar louca' in normalized(context['answer']):reply='Lavar louça é uma ótima candidata a tarefa chata! O que mais incomoda nessa rotina: o tempo ou aquela pilha depois de cozinhar?'
            else:reply='Boa! Tem um caminho interessante nessa ideia. Dá para explorar com calma, sem transformar o papo numa entrevista.'
            return {**context,'reply':reply}

    def snapshot(self):
        with self.lock:
            q=self.current
            if not q:return {'PRESENTER_QUESTION_WINDOW':'INATIVA'}
            return {'PRESENTER_QUESTION_WINDOW':'ATIVA' if self.clock()<q['expires_at'] else 'EXPIRADA',
                **{k:q[k] for k in ('question_id','expected_response_type','opened_at','expires_at')},
                'responses':len(q['responses']),'unique_authors':len(q['authors'])}
