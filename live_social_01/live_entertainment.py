"""Safe local variety for Presenter speech. Selection has no IO or model calls."""
import re
import unicodedata
from collections import Counter, deque
from dataclasses import dataclass


JOKES = (
    'Por que o computador foi ao médico? Porque pegou um vírus.',
    'Qual é o café favorito do programador? Java. Essa veio com açúcar ou com erro de compilação?',
    'Por que o livro de matemática ficou preocupado? Porque estava cheio de problemas.',
    'O que o zero disse para o oito? Belo cinto!',
    'Por que o relógio foi à terapia? Porque estava passando por momentos difíceis.',
    'O que a impressora falou para a outra? Essa folha é sua ou é impressão minha?',
    'Como o astronauta serve o café? Em uma xícara espacial.',
    'Qual animal está sempre conectado? O porco-espinho, cheio de pontos de acesso.',
    'Por que o teclado pediu férias? Porque estava trabalhando sob muita pressão.',
    'O que o tomate foi fazer no banco? Tirar extrato.',
    'Por que o computador levou um casaco? Porque deixou o Windows aberto.',
    'Qual é o peixe que organiza a agenda? O peixe que nada deixa para amanhã.',
    'Por que a calculadora não discute? Porque prefere resolver tudo na conta.',
    'Por que o robô levou uma escada? Para subir de nível.',
    'O que a tomada disse para o carregador? Nossa conexão tem muita energia.',
    'Por que o lápis foi promovido? Porque sempre tinha uma ponta de ideia.',
)

# Categories describe audience content; action kinds retain the existing CTA protocol.
KINDS = {'HUMOR':'JOKE', 'PERGUNTA_DIVERTIDA':'QUESTION_TO_AUDIENCE',
    'CURIOSIDADE':'CURIOSITY', 'TECNOLOGIA_LEVE':'TOPIC_CONTINUE', 'IA':'TOPIC_START',
    'COTIDIANO':'SILENCE_FILL', 'DESAFIO_CHAT':'CHALLENGE', 'JOGO_RAPIDO':'QUICK_GAME',
    'OPINIAO_AUDIENCIA':'AUDIENCE_OPINION', 'HISTORIA_LEVE':'LIGHT_STORY',
    'CTA_CHAT':'CHAT_CTA', 'CTA_LIKE':'LIKE_CTA', 'CTA_FOLLOW':'FOLLOW_CTA',
    'CTA_GIFT':'GIFT_CTA', 'JARVIS_PROJECT':'DEMONSTRATION_PROMPT'}
CONTENT = {
    'PERGUNTA_DIVERTIDA':(
        'Se vocês pudessem automatizar uma tarefa chata da vida, qual seria? Eu colocaria a dobragem de roupa na disputa. Quero ver as ideias do chat.',
        'Pergunta de sobrevivência: vocês são time café, chá ou energético? Vale defender a escolha com uma frase. Só não vale transformar a resposta em guerra de bebidas.'),
    'CURIOSIDADE':(
        'Uma curiosidade simples: no sistema binário usamos zero e um. Dá para montar muita coisa com só duas opções. Que invenção parece simples, mas surpreende vocês?',
        'Já repararam como um cheiro ou uma música pode lembrar uma situação antiga? Sem precisar contar nada pessoal, qual som vocês associam a uma época boa?'),
    'TECNOLOGIA_LEVE':(
        'Qual tecnologia vocês achavam coisa de filme e hoje virou parte do cotidiano? Pode ser chamada de vídeo ou mapa no celular. Quero ouvir uma escolha do chat.',
        'Vamos escolher um conforto tecnológico para levar a uma ilha imaginária: câmera, música ou mapa? Sem resolver tudo com uma resposta mágica. Qual desses vocês escolheriam primeiro?'),
    'IA':(
        'Se uma IA pudesse fazer uma tarefa chata por vocês agora, qual seria? Eu quero uma ideia prática, daquelas que realmente poupam tempo e deixam o dia mais leve.',
        'Uma IA que arruma a agenda ou uma que inventa receitas com o que tem na geladeira? Qual dessas vocês usariam mais? Essa disputa mistura organização com fome.'),
    'COTIDIANO':(
        'Tem uma grande discussão cotidiana esperando resposta: colocar despertador cinco minutos antes ajuda ou só cria mais cinco minutos de negociação? Qual é a estratégia de vocês?',
        'Vamos falar de pequenas vitórias: achar uma meia perdida, pegar todos os sinais verdes ou terminar uma tarefa antes do prazo? Qual merece a maior comemoração?'),
    'DESAFIO_CHAT':(
        'Desafio rápido: descrevam uma invenção útil usando só três palavras. Pode ser uma ideia completamente imaginária. Quero ver criatividade sem precisar de um manual de instruções inteiro.',
        'Desafio do chat: inventem um nome para um robô que só cuida de plantas. Quero criatividade na resposta. Será que aparece um jardineiro com nome de super-herói?'),
    'JOGO_RAPIDO':(
        'A ou B, sem pensar demais: celular ou computador? Escolham um e deem um motivo curto. Quero acompanhar as escolhas, sem declarar vencedor antes das respostas.',
        'Complete a frase: se eu tivesse um botão mágico em casa, ele faria... Vale uma tarefa bem cotidiana ou uma ideia absurda. Manda uma opção no chat.'),
    'OPINIAO_AUDIENCIA':(
        'Vocês preferem aprender assistindo alguém fazer ou colocando a mão na massa logo de cara? Pode escolher os dois, mas quero saber qual vem primeiro para vocês.',
        'Uma viagem curta toda semana ou uma viagem longa por ano? É só uma escolha imaginária, sem planejar gastos. Qual combina mais com o estilo de vocês?'),
    'HISTORIA_LEVE':(
        'Imagina esta cena fictícia: um robô foi organizar a cozinha e separou os biscoitos por ordem alfabética. Ficou organizado, mas alguém ainda precisava achar o café. Como vocês terminariam essa história?',
        'Cena inventada: uma casa inteligente decidiu que segunda-feira precisava de música de aventura. O despertador virou trilha de missão. Que som vocês escolheriam para começar o dia?'),
    'CTA_CHAT':(
        'Manda uma pergunta ou um assunto para a gente conversar, pessoal. Pode ser cotidiano, tecnologia ou uma ideia divertida. Quero saber o que está despertando a curiosidade de vocês.',
        'Quero ouvir o chat: escolham um tema para a próxima conversa. Vale uma dúvida simples ou uma pergunta criativa. A participação de vocês muda o rumo da Live.'),
    'CTA_LIKE':(
        'Se vocês estão curtindo a conversa, fortaleçam a Live com um like. E me contem qual assunto merece continuar; uma boa pergunta também ajuda bastante a animar esse encontro.',
        'Quem está gostando desse papo pode deixar um like para apoiar a transmissão. Sem pressão, pessoal. Quero ver também uma ideia do chat para a próxima rodada de conversa.'),
    'CTA_FOLLOW':(
        'Se esse tipo de conversa combina com vocês, acompanhem o canal para encontrar as próximas transmissões. Agora me contem um assunto que gostariam de ver numa outra Live.',
        'Quem quiser voltar para os próximos encontros pode acompanhar o canal. Por aqui cabe pergunta, curiosidade e bom humor. Que tema vocês colocariam na lista para outra conversa?'),
    'CTA_GIFT':(
        'Quem quiser apoiar pela opção de presente disponível, eu agradeço. É opcional, pessoal; participar do chat também conta muito para manter a conversa animada. Bora seguir com as ideias.',
        'Se quiserem fortalecer a transmissão com a opção de presente disponível, fica o convite. Sem obrigação: uma pergunta ou uma boa ideia no chat já ajuda a conversa a acontecer.'),
    'JARVIS_PROJECT':(
        'Eu sou o JARVIS, um assistente desenvolvido pelo Rodineles. O projeto junta conversa e voz para participar da Live. Qual demonstração disponível vocês gostariam de conhecer, sem entrar num manual técnico?',
        'Rodineles, quando você quiser, podemos mostrar uma demonstração disponível do JARVIS. A ideia é ver na prática e explicar de um jeito simples. O que o chat gostaria de perguntar?'),
}
TOPICS = {
    'futebol':('futebol','campeonato'), 'indústria':('industria','industrial'),
    'trabalho':('trabalho','profissao'), 'histórias':('historias','historia'),
    'humor':('piada','piadas','humor'),
    'carros':('carro','carros','automovel'), 'música':('musica','musicas'),
    'jogos':('jogo','jogos','videogame'), 'comida':('comida','culinaria','receitas'),
    'viagens':('viagem','viagens'), 'programação':('python','programacao','codigo'),
    'tecnologia':('tecnologia','celular','smartphone'), 'IA':('inteligencia artificial','gemini'),
    'JARVIS':('jarvis','arquitetura_jarvis'),
}


def normalized(text):
    text=unicodedata.normalize('NFKD',text.casefold())
    return ' '.join(re.findall(r'[a-z0-9]+',''.join(c for c in text if not unicodedata.combining(c))))


@dataclass(frozen=True)
class ContentChoice:
    category: str
    kind: str
    text: str
    topic: str
    content_id: str


class LiveContentMix:
    """Read-only proposals; record only speech that was actually delivered."""
    def __init__(self): self.reset()

    def reset(self):
        self.recent_categories=deque(maxlen=60); self.recent_jokes=deque(maxlen=len(JOKES))
        self.uses=Counter(); self.cursor=0; self.topic=None; self.topic_at=0.

    def observe_topic(self,text,now):
        value=normalized(text)
        # Only public labels survive, never raw comments or personal information.
        if not re.search(r'\b(falar|conversar|assunto|sobre|prefiro|prefere|gosto|curto|qual|como)\b',value):return
        for topic,words in TOPICS.items():
            if any(re.search(r'\b'+re.escape(word)+r'\b',value) for word in words):
                self.topic,self.topic_at=topic,now;return

    def sync_topic(self,topic,now):
        mapping={'python':'programação','programacao':'programação','celular':'tecnologia','gemini':'IA'}
        if topic in mapping and self.topic is None:self.topic,self.topic_at=mapping[topic],now

    def active_topic(self,now):
        if self.topic and now-self.topic_at>=600:self.topic=None
        return self.topic

    def choose(self,now,last_by_kind,config,recent_texts,gift_enabled=False,next_topic=False,excluded_categories=()):
        topic=self.active_topic(now)
        counts=Counter(self.recent_categories); order=list(KINDS)
        rotated=order[self.cursor%len(order):]+order[:self.cursor%len(order)]
        eligible=[]
        for category in rotated:
            if category in excluded_categories:continue
            kind=KINDS[category]
            if category in list(self.recent_categories)[-2:]:continue
            if category=='CTA_GIFT' and not gift_enabled:continue
            if category.startswith('CTA_') and now-last_by_kind.get('CTA_GLOBAL',float('-inf'))<config.get('CTA_GLOBAL_COOLDOWN',90):continue
            if category=='JARVIS_PROJECT':
                if topic and topic!='JARVIS':continue
                if counts[category]+1>max(1,(len(self.recent_categories)+1)*.15):continue
            if now-last_by_kind.get(kind,float('-inf'))<config.get(kind,0):continue
            eligible.append(category)
        # Stable state-aware tie breaking; no fixed rotation/playlist. First joke retained.
        import hashlib
        def score(category):
            state=f'{self.cursor}:{topic}:{list(self.recent_categories)[-4:]}:{category}'
            tie=int.from_bytes(hashlib.blake2s(state.encode(),digest_size=4).digest(),'big')/2**32
            if not self.recent_categories and category=='HUMOR':return (-1,0)
            return (counts[category],tie)
        for category in sorted(eligible,key=score):
            kind=KINDS[category]
            if category=='HUMOR':
                for index,joke in enumerate(JOKES):
                    if index not in self.recent_jokes:
                        text=joke+' Essa veio do banco das piadas ruins com orgulho. Vocês preferem uma dessas ou uma pergunta divertida na próxima rodada?'
                        if text not in recent_texts:return ContentChoice(category,kind,text,'humor',f'joke:{index}')
                # No recycling an exhausted joke bank in this session.
                continue
            cards=CONTENT[category]
            if topic and topic!='JARVIS' and category in {'PERGUNTA_DIVERTIDA','OPINIAO_AUDIENCIA','DESAFIO_CHAT','TECNOLOGIA_LEVE'} and not next_topic:
                contextual={
                    'PERGUNTA_DIVERTIDA':(
                        f'Vocês puxaram {topic}, então vamos continuar por aí. Se pudessem inventar uma novidade nesse assunto, qual seria? Vale uma ideia prática ou uma completamente imaginária.',
                        f'Pergunta divertida sobre {topic}: se esse tema virasse um filme, seria comédia ou aventura? Quero ouvir a escolha de vocês e um motivo curto no chat.'),
                    'OPINIAO_AUDIENCIA':(
                        f'Seguindo o assunto de {topic}: o que vocês valorizam mais, praticidade ou uma ideia surpreendente? Dá para preferir os dois, mas quero saber qual vocês colocariam primeiro.',
                        f'Vamos ouvir uma opinião sobre {topic}: vocês preferem conhecer os detalhes ou ir direto para a experiência prática? Qual caminho deixa esse assunto mais interessante para vocês?'),
                    'DESAFIO_CHAT':(
                        f'Desafio sobre {topic}: descrevam esse assunto usando apenas três palavras. Sem precisar contar nada pessoal. Quero ver se o chat consegue resumir uma ideia grande em poucas palavras.',
                        f'Dinâmica rápida com {topic}: inventem um título divertido para uma apresentação desse assunto. Pode ser criativo, sem atacar ninguém. Qual título vocês colocariam no cartaz?'),
                    'TECNOLOGIA_LEVE':(
                        f'Continuando com {topic}, qual parte desse assunto vocês acham que poderia ficar mais simples? Quero uma ideia do cotidiano, sem transformar a conversa numa aula cheia de termos difíceis.',
                        f'No assunto de {topic}, o que vocês mostrariam primeiro para alguém curioso? Manda uma escolha e um motivo curto. Assim a conversa segue pelo interesse de vocês.')}
                cards=contextual[category]
            prefixes=('','Bora conversar, pessoal. ','Tenho uma para o chat. ','Mudando um pouco o ritmo. ')
            options=[]
            for i,body in enumerate(cards):
                for v,prefix in enumerate(prefixes):
                    ident=f'{category}:{topic or "geral"}:{i}:{v}'
                    text=prefix+body
                    if text not in recent_texts:options.append((self.uses[ident],ident,text))
            if options:
                _,ident,text=min(options,key=lambda row:row[0])
                return ContentChoice(category,'TOPIC_TRANSITION' if next_topic else kind,text,
                    topic if topic and not next_topic else category.lower(),ident)
        return None

    def record(self,choice):
        self.recent_categories.append(choice.category); self.uses[choice.content_id]+=1
        if choice.content_id.startswith('joke:'):self.recent_jokes.append(int(choice.content_id.split(':')[1]))
        self.cursor+=1
