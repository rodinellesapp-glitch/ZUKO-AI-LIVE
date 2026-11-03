"""Deterministic, per-author topic state for the current Live only."""
from __future__ import annotations

import re
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from threading import Lock
from live_cohost import current_intent

QUESTION_TTL_SECONDS = 5 * 60
AUTHOR_LIMIT = 20


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


TOPIC_WORDS = {
    "celular": {"celular", "smartphone", "telefone", "aparelho"},
    "robotica": {"robo", "robotica", "sensor", "sensores", "motor", "motores", "arduino"},
    "programacao": {"programacao", "codigo", "python", "javascript", "web", "software"},
    "carro": {"carro", "automovel", "veiculo", "motorista"},
    "fisica": {"fisica", "mecanica quantica", "gravidade"},
    "futebol": {"futebol", "jogo de futebol", "time", "campeonato"},
}
SWITCH_SIGNALS = re.compile(
    r"\b(?:agora quero falar de|mudando de assunto|quero aprender|quero criar|vamos falar de|"
    r"e sobre|outra coisa|quero saber de)\b"
)
QUESTION_STOPWORDS = {"qual", "que", "voce", "vc", "o", "a", "de", "do", "da", "para", "pra", "mais"}


@dataclass(frozen=True)
class ConversationUpdate:
    active_topic: str
    active_intent: str
    facts: dict[str, str]
    switched_from: str = ""
    pending_cleared: bool = False


@dataclass
class AuthorState:
    active_topic: str = "geral"
    active_intent: str = ""
    topic_facts: dict[str, dict[str, str]] = field(default_factory=dict)
    recent_turns: deque[str] = field(default_factory=lambda: deque(maxlen=5))
    user_questions: deque[tuple[str, float]] = field(default_factory=lambda: deque(maxlen=3))
    jarvis_questions: deque[tuple[str, float]] = field(default_factory=lambda: deque(maxlen=3))
    conversation_goal: str = ""
    current_stage: str = "início"
    delivered_points: set[str] = field(default_factory=set)
    planned_points: set[str] = field(default_factory=set)
    declared_assets: set[str] = field(default_factory=set)
    completed_actions: set[str] = field(default_factory=set)
    next_useful_step: str = "entender necessidade"
    updated_at: float = 0.0


class ConversationState:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._authors: OrderedDict[str, AuthorState] = OrderedDict()
        self._lock = Lock()
        self.topic_switches = 0
        self.pending_cleared = 0
        self.dialogue_advances = 0
        self.dialogue_repeats_prevented = 0

    @staticmethod
    def _goal(topic: str, intent: str) -> str:
        if topic == "robotica": return "criar primeiro robô"
        if topic == "celular": return "escolher celular"
        if topic == "programacao": return "aprender programação"
        return intent or "conversar sobre o assunto"

    @staticmethod
    def _explicit_repeat(value: str) -> bool:
        return bool(re.search(r"\b(?:nao entendi|explica de novo|como funciona mesmo|repete|explica mais simples)\b", value))

    @staticmethod
    def _requested_stage(value: str) -> str:
        if re.search(r"\b(?:o que (?:eu )?preciso comprar|componentes|pecas|peças|lista)\b", value): return "lista_componentes"
        if re.search(r"\b(?:e depois|montagem|como (?:eu )?monto|como montar|ligar|ligacoes)\b", value): return "montagem"
        if re.search(r"\b(?:como funciona|funcionamento)\b", value): return "funcionamento"
        if re.search(r"\b(?:qual (?:voce )?(?:recomenda|indica)|qual eu compro|qual (?:e )?melhor para mim|me recomenda um|qual escolher|recomendacao)\b", value): return "recomendacao"
        return ""

    @staticmethod
    def detect_topic(text: str, current: str = "geral") -> str:
        if current_intent(text)=='JOKE_REQUEST':return 'humor'
        normalized = normalize(text)
        scores = {topic: sum(1 for word in words if re.search(rf"\b{re.escape(word)}\b", normalized))
                  for topic, words in TOPIC_WORDS.items()}
        candidate = max(scores, key=scores.get)
        if not scores[candidate]:
            return current
        # Python is commonly a fact inside robotics; switch only on a clear programming intent.
        if current == "robotica" and candidate == "programacao" and not re.search(
                r"\b(?:quero aprender|vamos falar de|e sobre|programacao|codigo|web|software)\b", normalized):
            return current
        if current != "geral" and candidate != current and not SWITCH_SIGNALS.search(normalized):
            # A clear domain noun still constitutes a strong switch.
            if scores[candidate] < 1 or candidate == "programacao" and normalized in {"python", "com python"}:
                return current
        return candidate

    @staticmethod
    def _intent(text: str, previous: str) -> str:
        if current_intent(text)=='JOKE_REQUEST':return 'JOKE_REQUEST'
        value = normalize(text)
        if re.search(r"\b(?:qual (?:voce )?(?:recomenda|indica)|qual eu compro|qual (?:e )?melhor para mim|me recomenda um|qual comprar)\b", value): return "RECOMMENDATION_REQUEST"
        if re.search(r"\b(?:recomenda|recomendacao)\b", value): return "RECOMMENDATION_REQUEST"
        if re.search(r"\b(?:comecar|por onde)\b", value): return "comecar"
        if re.search(r"\b(?:quero comprar|comprar)\b", value): return "comprar"
        if re.search(r"\b(?:quero criar|criar|montar)\b", value): return "criar projeto"
        if re.search(r"\b(?:quero aprender|aprender)\b", value): return "aprender"
        return previous

    @staticmethod
    def _facts(text: str, topic: str) -> dict[str, str]:
        value = normalize(text)
        facts = {}
        if topic == "celular":
            budget = re.search(r"(?:r\s*)?(\d{1,3}(?:[. ]\d{3})+|\d{3,5})", value)
            if budget:
                facts["budget"] = budget.group(1).replace(".", "").replace(" ", "")
            if re.search(r"\b(?:jogar|jogos|game|games)\b", value): facts["usage"] = "jogos"
            if "trabalho" in value: facts["usage"] = "trabalho"
        if topic in {"robotica", "programacao"}:
            if "python" in value: facts["language"] = "Python"
            if re.search(r"\b(?:iniciante|comecando|nunca programei)\b", value): facts["level"] = "iniciante"
            if re.search(r"\b(?:por onde comecar|nao sei por onde)\b", value): facts["goal"] = "começar"
        return facts

    def update(self, author: str, text: str) -> ConversationUpdate:
        now = self._clock()
        with self._lock:
            state = self._authors.setdefault(author, AuthorState())
            previous = state.active_topic
            topic = self.detect_topic(text, previous)
            switched = previous not in {"", "geral"} and topic != previous
            if switched:
                self.topic_switches += 1
                state.recent_turns.clear()
                state.user_questions.clear(); state.jarvis_questions.clear()
                state.active_intent = ""
                state.conversation_goal, state.current_stage = "", "início"
                state.delivered_points.clear(); state.planned_points.clear(); state.declared_assets.clear(); state.completed_actions.clear()
                state.next_useful_step = "entender necessidade"
            state.active_topic = topic
            state.active_intent = self._intent(text, state.active_intent)
            state.conversation_goal = self._goal(topic, state.active_intent)
            requested = self._requested_stage(normalize(text))
            if requested:
                if requested in state.delivered_points and not self._explicit_repeat(normalize(text)):
                    self.dialogue_repeats_prevented += 1
                    state.current_stage = state.next_useful_step
                else:
                    state.current_stage = requested
            elif self._explicit_repeat(normalize(text)):
                if "funcionamento_sensores" in state.delivered_points:
                    state.current_stage = "funcionamento"
                elif state.delivered_points:
                    state.current_stage = "revisão"
            facts = state.topic_facts.setdefault(topic, {})
            facts.update(self._facts(text, topic))
            if "?" in text or state.active_intent == "RECOMMENDATION_REQUEST":
                state.user_questions.append((text[:180], now))
            self._record_declared_facts(state, text)
            state.recent_turns.append(text[:180])
            state.updated_at = now
            self._authors.move_to_end(author)
            while len(self._authors) > AUTHOR_LIMIT:
                self._authors.popitem(last=False)
            if state.next_useful_step and state.next_useful_step not in state.delivered_points:
                state.planned_points = {state.next_useful_step}
            return ConversationUpdate(topic, state.active_intent, dict(facts), previous if switched else "", False)

    @staticmethod
    def _record_declared_facts(state: AuthorState, text: str) -> None:
        value = normalize(text)
        declared = re.search(r"\b(?:eu tenho|tenho|comprei|possuo|ja montei|montei|ja programei|programei|ja testei|testei|ja fiz|fiz|criei|escrevi)\b", value)
        if not declared:
            return
        for key, pattern in {"codigo": r"\b(?:codigo|programa)\b", "kit": r"\bkit\b", "arduino": r"\barduino\b",
                             "raspberry_pi": r"\braspberry pi\b", "componentes": r"\b(?:componentes|pecas)\b",
                             "hardware": r"\bhardware\b", "robo": r"\brobo\b"}.items():
            if re.search(pattern, value):
                state.declared_assets.add(key)
        if re.search(r"\b(?:ja montei|montei|ja constru[iu]|constru[iu])\b", value): state.completed_actions.add("montagem")
        if re.search(r"\b(?:ja programei|programei|escrevi|criei)\b", value): state.completed_actions.add("codigo")
        if re.search(r"\b(?:ja testei|testei)\b", value): state.completed_actions.add("teste")

    def record_response(self, author: str, response: str) -> None:
        """Save compact delivered concepts, never the full response."""
        value = normalize(response)
        with self._lock:
            state = self._authors.setdefault(author, AuthorState())
            markers: list[tuple[str, str, tuple[str, ...], str]] = []
            if state.active_topic == "robotica":
                markers = [("sugestao_seguidor_linha", "funcionamento", ("seguidor de linha",)),
                           ("funcionamento_sensores", "lista_componentes", ("sensor", "linha preta", "infravermelho")),
                           ("lista_componentes", "montagem", ("esp32", "chassi", "dois motores", "driver", "sensor de linha", "jumpers")),
                           ("montagem", "codigo_python", ("fixe os motores", "ligue os motores", "compartilhe o gnd", "teste as rodas suspensas")),
                           ("codigo_python", "teste", ("python", "micro python", "micropython"))]
            elif state.active_topic == "celular":
                markers = [("criterios_desempenho", "recomendacao_concreta", ("processador", "ram", "desempenho")),
                           ("recomendacao_concreta", "comparar_opcoes", ("intermediario", "seminovo", "celular gamer", "linha intermediaria"))]
            elif state.active_topic == "programacao":
                markers = [("primeiro_passo", "pratica", ("primeiro passo", "comeca por", "comece por"))]
            for point, next_step, terms in markers:
                threshold = 3 if point == "lista_componentes" else (2 if point == "criterios_desempenho" else 1)
                if sum(term in value for term in terms) >= threshold:
                    if point not in state.delivered_points:
                        state.delivered_points.add(point); self.dialogue_advances += 1
                    state.planned_points.discard(point)
                    state.current_stage, state.next_useful_step = point, next_step
                    if next_step not in state.delivered_points:
                        state.planned_points = {next_step}

    def mark_pending_cleared(self) -> None:
        with self._lock:
            self.pending_cleared += 1

    def reset(self) -> None:
        with self._lock:
            self._authors.clear()
            self.topic_switches = 0
            self.pending_cleared = 0
            self.dialogue_advances = self.dialogue_repeats_prevented = 0

    def reset_author(self, author: str) -> None:
        with self._lock:
            self._authors.pop(author, None)

    def prompt_context(self, author: str) -> str:
        with self._lock:
            state = self._authors.get(author)
            if not state: return ""
            facts = ", ".join(f"{key}={value}" for key, value in state.topic_facts.get(state.active_topic, {}).items()) or "nenhum"
            questions = self._questions(state.jarvis_questions)
            delivered = ", ".join(sorted(state.delivered_points)) or "nenhum"
            planned = ", ".join(sorted(state.planned_points)) or "nenhum"
            turns = " | ".join(state.recent_turns)[-360:] or "nenhum"
            active_intent = 'recomendacao (RECOMMENDATION_REQUEST)' if state.active_intent == 'RECOMMENDATION_REQUEST' else (state.active_intent or 'não definida')
            result = (f"ESTADO ATIVO DO MESMO AUTOR: tópico={state.active_topic}; intenção={active_intent}; "
                    f"fatos deste tópico={facts}; objetivo={state.conversation_goal or 'não definido'}; "
                    f"etapa atual={state.current_stage}; DELIVERED (conteúdo efetivamente respondido)={delivered}; "
                    f"PLANNED (sugestão futura, nunca já explicado)={planned}; próximo passo útil={state.next_useful_step}; "
                    f"turnos recentes={turns}; perguntas recentes já feitas={questions or 'nenhuma'}. "
                    "Só os itens DELIVERED podem ser descritos como já explicados/vistos/falados. PLANNED não é histórico realizado. "
                    "CURRENT_USER_INTENT da mensagem atual tem prioridade absoluta; pergunta pendente do JARVIS é contexto secundário.")
            if state.active_topic == 'robotica' and state.current_stage == 'lista_componentes':
                result += (" ANSWER_FIRST obrigatório: liste peças concretas para um primeiro robô móvel com Python: "
                           "placa ESP32 com MicroPython, chassi 2WD, dois motores, driver compatível, sensor de linha, "
                           "cabos jumper e alimentação compatível. Não diga que o autor já possui qualquer peça.")
            elif state.active_topic == 'robotica' and state.current_stage == 'montagem':
                result += (" ANSWER_FIRST obrigatório: explique passos de montagem agora: fixar motores no chassi, "
                           "instalar o sensor, ligar motores ao driver, sinais do driver à placa, compartilhar GND, "
                           "conectar alimentação compatível e testar motores suspensos antes de apoiar no chão. "
                           "Não invente peças já compradas ou montagem já feita.")
            elif state.active_topic == 'celular' and state.current_stage == 'recomendacao':
                result += (" ANSWER_FIRST: recomende perfil de aparelho usando orçamento e uso registrados; "
                           "não invente modelo, preço atual ou preferência. Responda antes de perguntar.")
            result += (f" GROUNDING: fatos explicitamente declarados pelo autor={','.join(sorted(state.declared_assets)) or 'nenhum'}; "
                       "desejo, plano ou sugestão não prova posse, compra, experiência ou trabalho já feito. "
                       "Afirme posse somente se o autor a declarou; sem isso, use condição ou possibilidade.")
            return result

    def ground_response(self, author: str, response: str) -> str:
        """Rewrite only explicit unsupported possession claims about project assets."""
        with self._lock:
            state = self._authors.get(author)
            if not state:
                return response
            result = response
            patterns = [("codigo", "codigo", r"(?:o\s+)?(?:seu\s+)?(?:c[oó]digo|programa)", r"(?:montou|fez|criou|escreveu|programou)"),
                        ("montagem", "kit", r"(?:o\s+)?(?:seu\s+)?kit", r"(?:montou|fez|comprou|testou)"),
                        ("montagem", "arduino", r"(?:o\s+)?(?:seu\s+)?arduino", r"(?:tem|possui|comprou|montou|testou)"),
                        ("montagem", "raspberry_pi", r"(?:o\s+)?(?:seu\s+)?raspberry\s*pi", r"(?:tem|possui|comprou|montou|testou)"),
                        ("montagem", "componentes", r"(?:os\s+)?(?:seus\s+)?(?:componentes|peças)", r"(?:tem|possui|comprou|montou|testou)"),
                        ("montagem", "hardware", r"(?:o\s+)?(?:seu\s+)?hardware", r"(?:tem|possui|comprou|montou|testou)"),
                        ("montagem", "robo", r"(?:o\s+)?(?:seu\s+)?rob[oô]", r"(?:tem|possui|comprou|montou|construiu|fez|testou)")]
            for action, asset, noun, verb in patterns:
                if asset in state.declared_assets or action in state.completed_actions:
                    continue
                result = re.sub(rf"\b{noun}\s+que\s+voc[eê]\s+(?:j[aá]\s+)?{verb}\b",
                                "um código que você poderá criar" if asset == "codigo" else "um item que você poderá preparar",
                                result, flags=re.IGNORECASE)
                result = re.sub(rf"\b(voc[eê]\s+(?:j[aá]\s+)?{verb})\s+{noun}\b",
                                "quando você preparar esse item", result, flags=re.IGNORECASE)
                bare_noun = noun.replace(r"(?:o\s+)?", "").replace(r"(?:seu\s+)?", "").replace(r"(?:os\s+)?", "").replace(r"(?:seus\s+)?", "")
                for prep, replacement in (("no seu", "em um"), ("na sua", "em uma"), ("do seu", "de um"), ("da sua", "de uma")):
                    result = re.sub(rf"\b{prep}\s+{bare_noun}\b", f"{replacement} {asset.replace('_', ' ')}", result, flags=re.IGNORECASE)
                result = re.sub(rf"\b(?:o\s+)?seu\s+{bare_noun}\b", f"um {asset.replace('_', ' ')}", result, flags=re.IGNORECASE)
                result = re.sub(rf"\b(?:a\s+)?sua\s+{bare_noun}\b", f"uma {asset.replace('_', ' ')}", result, flags=re.IGNORECASE)
            if not state.delivered_points:
                result = re.sub(r"\bj[aá]\s+falamos\b", "Podemos falar", result, flags=re.IGNORECASE)
                result = re.sub(r"\bj[aá]\s+(vimos|explicamos|abordamos)\b", "Podemos abordar", result, flags=re.IGNORECASE)
            else:
                delivered_synonyms = {"codigo_python": r"c[oó]digo(?:\s+python)?", "montagem": r"montagem", "lista_componentes": r"componentes|peças", "recomendacao_concreta": r"recomenda[cç][aã]o", "teste": r"teste"}
                for point, term in delivered_synonyms.items():
                    if point in state.delivered_points:
                        continue
                    pattern = rf"[^.!?]*\bj[aá]\s+(?:falamos|vimos|explicamos|abordamos)\s+(?:sobre\s+)?[^.!?]*{term}[^.!?]*[.!?]?"
                    result = re.sub(pattern, "Ainda podemos abordar esse ponto.", result, flags=re.IGNORECASE)
                result = re.sub(r"\bj[aá]\s+(?:falamos|vimos|explicamos|abordamos)\b", "Podemos retomar", result, flags=re.IGNORECASE)
            return result

    def answer_first_guard(self, author: str, current_text: str, response: str) -> str:
        """Supply a concise domain answer only when the direct requested stage is missing."""
        with self._lock:
            state=self._authors.get(author)
            if not state: return response
            value=normalize(current_text); answer=normalize(response)
            if state.active_topic=='robotica' and state.current_stage=='lista_componentes' and re.search(r'\b(?:comprar|pecas|componentes|preciso)\b',value):
                if not set(answer.split()) & {'esp32','arduino','motor','driver','chassi','sensor','jumper'}:
                    return ("Para começar, procure uma ESP32 compatível com MicroPython, chassi 2WD, dois motores, "
                            "driver compatível, sensor de linha, jumpers e alimentação adequada. Confira a tensão "
                            "de cada peça; você ainda não precisa ter comprado nada. " + response).strip()
            if state.active_topic=='robotica' and state.current_stage=='montagem' and re.search(r'\b(?:como|montar|monto|monta|montagem)\b',value):
                if not set(answer.split()) & {'fixe','prenda','ligue','conecte','instale','monte'}:
                    return ("Fixe os motores no chassi, instale o sensor na frente, ligue os motores ao driver e "
                            "os sinais do driver à ESP32. Una os GNDs, confira a alimentação e teste as rodas "
                            "suspensas antes de colocar o robô no chão. " + response).strip()
            if state.active_topic=='celular' and state.active_intent=='RECOMMENDATION_REQUEST':
                facts=state.topic_facts.get('celular',{})
                budget=f"na faixa de até R$ {facts['budget']}" if facts.get('budget') else 'dentro do orçamento que você definir'
                usage='voltado para jogos' if facts.get('usage')=='jogos' else 'equilibrado para seu uso'
                categories={'intermediario','seminovo','gamer','entrada','linha'}
                has_direction=bool(categories & set(answer.split()))
                if not has_direction:
                    return (f"Minha direção seria um celular intermediário seminovo bem conservado, {usage}, {budget}; "
                            "priorize processador/chipset forte e pelo menos 8 GB de RAM, e confirme preço e disponibilidade atuais antes de comprar. "
                            + response).strip()
                if not re.search(r"\b(?:confirme|verifique|pre[cç]o|disponibilidade)\b", answer):
                    return response.rstrip(".!? ") + ". Confirme o preço e a disponibilidade atuais antes de comprar."
            return response

    def _questions(self, questions: deque[tuple[str, float]]) -> str:
        now = self._clock()
        while questions and now - questions[0][1] > QUESTION_TTL_SECONDS:
            questions.popleft()
        return " | ".join(question for question, _ in questions)

    @staticmethod
    def _equivalent(left: str, right: str) -> bool:
        a = set(normalize(left).split()) - QUESTION_STOPWORDS
        b = set(normalize(right).split()) - QUESTION_STOPWORDS
        return bool(a and b and (a == b or len(a & b) / max(len(a), len(b)) >= .7))

    def filter_and_record_questions(self, author: str, response: str) -> tuple[str, bool]:
        with self._lock:
            state = self._authors.setdefault(author, AuthorState())
            previous = [question for question, _ in state.jarvis_questions if self._clock() - _ <= QUESTION_TTL_SECONDS]
            parts = re.split(r"(?<=[.!?])\s+", response.strip())
            kept, suppressed = [], False
            best_similarity = 0.0
            for part in parts:
                similarities = [len((set(normalize(part).split()) - QUESTION_STOPWORDS) &
                                    (set(normalize(old).split()) - QUESTION_STOPWORDS)) /
                                max(1, len(set(normalize(part).split()) - QUESTION_STOPWORDS),
                                    len(set(normalize(old).split()) - QUESTION_STOPWORDS)) for old in previous]
                if "?" in part and any(self._equivalent(part, old) for old in previous):
                    suppressed = True
                    best_similarity = max(similarities, default=0.0)
                    continue
                kept.append(part)
                if "?" in part:
                    state.jarvis_questions.append((part.strip(), self._clock()))
            result = " ".join(kept).strip()
            self.last_question_suppression = {"source": "JARVIS", "match_source": "JARVIS", "similarity": best_similarity} if suppressed else {}
            return (result or "Com o que você já informou, dá para avançar sem repetir a mesma pergunta.", suppressed)

    def metrics(self, author: str) -> dict[str, object]:
        with self._lock:
            state = self._authors.get(author, AuthorState())
            return {"ACTIVE_TOPIC": state.active_topic, "TOPIC_SWITCHES_SESSION": self.topic_switches,
                    "CONTEXT_FACTS_COUNT": len(state.topic_facts.get(state.active_topic, {})),
                    "PENDING_QUESTION_CLEARED": self.pending_cleared,
                    "CONVERSATION_STAGE": state.current_stage,
                    "DELIVERED_POINTS_COUNT": len(state.delivered_points),
                    "PLANNED_POINTS_COUNT": len(state.planned_points),
                    "USER_QUESTIONS_HISTORY": len(state.user_questions),
                    "JARVIS_QUESTIONS_HISTORY": len(state.jarvis_questions),
                    "DIALOGUE_ADVANCES_SESSION": self.dialogue_advances,
                    "DIALOGUE_REPEATS_PREVENTED": self.dialogue_repeats_prevented}
