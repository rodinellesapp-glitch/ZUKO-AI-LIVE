"""Small deterministic selector for safe ZUKO live gestures."""
from dataclasses import dataclass
import re
import time
import unicodedata


@dataclass(frozen=True)
class Movement:
    animation: str
    priority: int
    cooldown: float
    emotion: str = 'calm'
    intent: str = 'comment'


class MovementSelector:
    SAFE_ANIMATIONS = frozenset({'Wave', 'Yes', 'No', 'Jump', 'Idle', 'Walk'})
    POSITIVE = ('obrigado', 'obrigada', 'legal', 'bom', 'boa', 'amei', 'gostei', 'sim', 'perfeito', 'parabens', 'top')
    NEGATIVE = ('nao gostei', 'ruim', 'chato', 'discordo', 'errado', 'pessimo')
    SPEECH_GESTURES = frozenset({'Idle', 'Wave', 'Yes', 'No', 'Jump'})
    SPEECH_COOLDOWN = 2.0
    JUMP_COOLDOWN = 25.0

    EMOTION_TERMS = {
        'gratitude': ('obrigado', 'obrigada', 'valeu', 'agradeco', 'grato', 'grata'),
        'empathy': ('sinto muito', 'que pena', 'meus sentimentos', 'forca', 'melhoras'),
        'sadness': ('triste', 'saudade', 'desanimado', 'sozinha', 'sozinho', 'chateado', 'chateada'),
        'frustration': ('irritado', 'irritada', 'pessimo', 'horrivel', 'que raiva', 'odeio', 'cansado'),
        'surprise': ('nossa', 'caramba', 'uau', 'serio', 'nao acredito', 'surpresa', 'surpreso'),
        'joy': ('feliz', 'adorei', 'amei', 'gostei', 'incrivel', 'maravilhoso', 'maravilhosa', 'parabens', 'perfeito', 'perfeita', 'legal', 'boa', 'bom', 'uhu', 'viva'),
    }

    def __init__(self, clock=time.monotonic, walk_seconds=180, rest_seconds=30):
        self.clock = clock
        self.walk_seconds, self.rest_seconds = self._valid_cycle(walk_seconds, rest_seconds)
        self.last_emit = float('-inf')
        self.last_wave = float('-inf')
        self.last_like = float('-inf')
        self.last_join = float('-inf')
        self.last_activity = clock()
        self.idle_walking = False
        self.idle_changed_at = self.last_activity
        self.walk_stop_pending = False
        self.last_speech_at = float('-inf')
        self.last_speech_jump = float('-inf')
        self.last_speech_animation = None
        self.last_speech_emotion = 'calm'
        self.last_speech_intent = 'comment'
        self.last_skip_reason = ''

    @staticmethod
    def _valid_cycle(walk_seconds, rest_seconds):
        def bounded(value, fallback):
            try:
                return max(1, min(3600, int(value)))
            except (TypeError, ValueError, OverflowError):
                return fallback
        return bounded(walk_seconds, 180), bounded(rest_seconds, 30)

    def set_idle_cycle(self, walk_seconds, rest_seconds):
        self.walk_seconds, self.rest_seconds = self._valid_cycle(walk_seconds, rest_seconds)
        self.idle_walking = False
        self.idle_changed_at = self.clock()
        self.walk_stop_pending = False
        return self.walk_seconds, self.rest_seconds

    @classmethod
    def emotion_for(cls, text):
        message = cls.normalize(text)
        for emotion in ('gratitude', 'empathy', 'sadness', 'frustration', 'surprise', 'joy'):
            if any(re.search(r'\b' + re.escape(term) + r'\b', message) for term in cls.EMOTION_TERMS[emotion]):
                return emotion
        return 'calm'

    @classmethod
    def intent_for(cls, text):
        message=cls.normalize(text)
        if re.match(r'^(oi|ola|e ai|bom dia|boa tarde|boa noite|bem vindo|bem vinda|salve)\b',message):return 'greeting'
        if re.search(r'\b(parabens|conseguimos|conquista|comemorar|comemoracao|vitoria|uhu|viva|mandou bem)\b',message):return 'celebration'
        if re.match(r'^(nao|discordo|nunca)\b|\b(nao recomendo|nao e correto|discordo|incorreto|errado)\b',message):return 'disagreement'
        if re.match(r'^(sim|concordo|exatamente|com certeza|claro|isso mesmo|correto|perfeito)\b',message):return 'affirmation'
        if cls.emotion_for(message) in {'empathy','sadness'}:return 'support'
        if '?' in str(text or '') or re.match(r'^(qual|como|onde|quando|por que|quem|quanto)\b',message):return 'question'
        return 'comment'

    @staticmethod
    def normalize(text):
        value = unicodedata.normalize('NFKD', str(text or '').casefold())
        value = ''.join(char for char in value if not unicodedata.combining(char))
        return re.sub(r'[^a-z0-9 ]+', ' ', value).strip()

    def choose(self, event_type, text='', provider=''):
        now = self.clock()
        kind = str(event_type or '').upper()
        message = self.normalize(text)
        self.last_skip_reason = ''
        interrupted_walk = self.idle_walking
        if kind in {'CHAT_MESSAGE','COMMENT','GEMINI_QUESTION','LIKE','LIKE_EVENT','REACTION','VIEWER_JOIN','FOLLOW','SUBSCRIBE','MEMBERSHIP','GIFT','GIFT_EVENT','SUPER_CHAT','DONATION'}:
            self.last_activity = now
            if self.idle_walking:
                self.idle_walking = False
                self.idle_changed_at = now
                self.walk_stop_pending = True
        if kind in {'LIKE','LIKE_EVENT','REACTION'} and now-self.last_like<8.0:
            self.last_skip_reason = 'cooldown'
            return None
        if kind=='VIEWER_JOIN' and now-self.last_join<10.0:
            self.last_skip_reason = 'cooldown'
            return None
        if kind in {'GIFT', 'GIFT_EVENT', 'SUPER_CHAT', 'DONATION'}:
            clip, priority = 'Jump', 5
        elif kind in {'FOLLOW', 'SUBSCRIBE', 'MEMBERSHIP'}:
            clip, priority = 'Yes', 4
        elif kind == 'VIEWER_JOIN':
            clip, priority = 'Wave', 2
        elif kind in {'LIKE', 'LIKE_EVENT', 'REACTION'}:
            clip, priority = 'Wave', 1
        elif kind in {'CHAT_MESSAGE', 'COMMENT'}:
            if any(re.search(r'\b' + re.escape(word) + r'\b', message) for word in self.NEGATIVE):
                clip, priority = 'No', 2
            elif self.emotion_for(message) in {'gratitude','joy'} or any(re.search(r'\b' + re.escape(word) + r'\b', message) for word in self.POSITIVE):
                clip, priority = 'Yes', 2
            elif self.emotion_for(message)=='surprise':
                clip,priority='Wave',2
            else:
                # Neutral chat does not request a separate event movement.
                self.last_skip_reason = 'no_matching_gesture'
                if interrupted_walk:
                    self.walk_stop_pending = False
                    return Movement('Idle', 0, 0.0)
                return None
        elif kind == 'GEMINI_QUESTION':
            clip, priority = 'Wave', 3
        else:
            self.last_skip_reason = 'unsupported_event'
            return None
        self.last_activity = now
        if now - self.last_emit < 1.0:
            self.last_skip_reason = 'cooldown'
            return None
        if clip == 'Wave' and now - self.last_wave < 10.0:
            if kind in {'LIKE', 'LIKE_EVENT', 'REACTION', 'VIEWER_JOIN'}:
                self.last_skip_reason = 'repetition'
                return None
            clip = 'Yes'
        self.last_emit = now
        self.last_activity = now
        if interrupted_walk:self.walk_stop_pending=False
        if kind in {'LIKE','LIKE_EVENT','REACTION'}:self.last_like=now
        if kind=='VIEWER_JOIN':self.last_join=now
        if clip == 'Wave':
            self.last_wave = now
        return Movement(clip, priority, 1.5,self.emotion_for(message),kind.lower())

    def speech_gesture(self, text, *, intent=None, emotion=None, intensity=1):
        """Choose one safe, local gesture for an entire spoken response."""
        now = self.clock()
        message = self.normalize(text)
        emotion = emotion if emotion in self.EMOTION_TERMS or emotion=='calm' else self.emotion_for(message)
        intent = intent if intent in {'greeting','celebration','disagreement','affirmation','support','question','comment'} else self.intent_for(text)
        if intensity==0:
            self.last_speech_at=now;self.last_speech_animation='Idle'
            self.last_speech_emotion=emotion;self.last_speech_intent=intent
            return 'Idle'
        if now - self.last_speech_at < self.SPEECH_COOLDOWN:
            self.last_speech_emotion = emotion
            self.last_speech_intent = intent
            return 'Idle'
        if len(message) > 240:
            self.last_speech_at = now
            self.last_speech_animation = 'Idle'
            self.last_speech_emotion = emotion
            self.last_speech_intent = intent
            return 'Idle'

        if intent=='greeting':
            candidate = 'Wave'
        elif intent=='celebration' and now - self.last_speech_jump >= self.JUMP_COOLDOWN:
            candidate = 'Jump'
        elif intent=='disagreement':
            candidate = 'No'
        elif intent=='affirmation':
            candidate = 'Yes'
        else:
            candidate = {
                'gratitude':'Yes','empathy':'Wave','sadness':'Wave',
                'surprise':'Wave','joy':'Yes',
            }.get(emotion,'Idle')

        if intensity==2 and candidate in {'Idle','Yes'} and intent in {'question','comment'} and emotion in {'calm','joy','surprise'}:
            candidate='Wave'

        if candidate == self.last_speech_animation:
            candidate = 'Idle'
        if candidate not in self.SPEECH_GESTURES:
            candidate = 'Idle'
        if candidate == 'Jump':
            self.last_speech_jump = now
        self.last_speech_at = now
        self.last_speech_animation = candidate
        self.last_speech_emotion = emotion
        self.last_speech_intent = intent
        return candidate

    def idle_action(self):
        """Toggle occasional world-travel walk after quiet periods; no queues."""
        now = self.clock()
        if self.walk_stop_pending:
            self.walk_stop_pending = False
            self.idle_changed_at = now
            return Movement('Idle', 0, 0.0)
        if self.idle_walking:
            if now - self.idle_changed_at >= self.walk_seconds:
                self.idle_walking = False
                self.idle_changed_at = now
                return Movement('Idle', 0, 0.0)
            return None
        if now - self.last_activity >= self.rest_seconds and now - self.idle_changed_at >= self.rest_seconds:
            self.idle_walking = True
            self.idle_changed_at = now
            return Movement('Walk', 0, 0.0)
        return None
