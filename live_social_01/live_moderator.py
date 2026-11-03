"""Conservative local triage. No platform actions, persistence or model access."""
import hashlib
import re
import threading
import time
import unicodedata
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass

@dataclass(frozen=True)
class ModeratorConfig:
    ttl: float = 300
    window_seconds: float = 10
    messages_per_window: int = 6
    duplicate_threshold: int = 2
    high_link_threshold: int = 4
    max_authors: int = 200
    max_history: int = 40
    max_reviews: int = 100
    excerpt_chars: int = 120
    repeated_chars: int = 12
    emoji_threshold: int = 10
    offensive_terms: tuple = ("idiota", "imbecil", "filho da puta")
    isolated_link: str = "REVIEW"
    promotion_severity: str = "LOW"

def normalize(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    return ' '.join(''.join(c for c in text if not unicodedata.combining(c)).split())

@dataclass(frozen=True)
class ModerationResult:
    category: str
    severity: str
    flags: tuple
    fingerprint: str
    suppress: bool
    presenter_allowed: bool

class LiveModeratorManager:
    def __init__(self, config=None, clock=time.monotonic):
        self.config, self.clock = config or ModeratorConfig(), clock
        self.lock = threading.RLock()
        self.recent_messages_by_author = OrderedDict()
        self.moderation_queue = OrderedDict()
        self.counts = Counter({name: 0 for name in ('MOD_MESSAGES_ANALYZED','MOD_SAFE','MOD_SPAM','MOD_FLOOD','MOD_DUPLICATE','MOD_SUSPICIOUS_LINK','MOD_SELF_PROMOTION','MOD_OFFENSIVE_POSSIBLE','MOD_HARASSMENT_POSSIBLE','MOD_HIGH_ALERTS','MOD_FALSE_POSITIVE_CLEARED')})
        self.last_alert = None
        self.serial = 0

    def _expire(self):
        now = self.clock()
        for author, rows in list(self.recent_messages_by_author.items()):
            while rows and now - rows[0][0] >= self.config.ttl: rows.popleft()
            if not rows: del self.recent_messages_by_author[author]
        for ident, row in list(self.moderation_queue.items()):
            if now - row['at'] >= self.config.ttl: del self.moderation_queue[ident]
        if self.last_alert and now-self.last_alert['at'] >= self.config.ttl: self.last_alert = None

    def analyze(self, author, text):
        with self.lock:
            self._expire()
            now, c = self.clock(), self.config
            author, text = str(author or 'ANÔNIMO')[:128], str(text or '')[:1000]
            value = normalize(text)
            fingerprint = hashlib.sha256(value.encode()).hexdigest()[:16]
            rows = self.recent_messages_by_author.setdefault(author, deque(maxlen=c.max_history))
            recent = [row for row in rows if now-row[0] < c.window_seconds]
            links = tuple(re.findall(r'(?:https?://|www\.)[^\s]+|\b[a-z0-9-]+\.(?:com|net|org|io|br)\b', value))
            duplicates = 1 + sum(row[1] == fingerprint for row in recent)
            link_count = 1 + sum(bool(set(links) & set(row[2])) for row in recent)
            flags = []
            if duplicates >= c.duplicate_threshold: flags.append('DUPLICATE')
            if len(recent)+1 > c.messages_per_window: flags.append('FLOOD')
            promotion = bool(re.search(r'\b(?:se inscreve no meu canal|entra no meu canal|me segue|me adiciona|link na bio)\b', value))
            if promotion: flags.append('SELF_PROMOTION')
            if links: flags.append('SUSPICIOUS_LINK' if promotion or duplicates > 1 or link_count > 1 or 'FLOOD' in flags else c.isolated_link)
            offensive = any(re.search(r'\b'+re.escape(normalize(term))+r'\b', value) for term in c.offensive_terms)
            if offensive:
                flags.append('OFFENSIVE_POSSIBLE')
                if re.search(r'\b(?:voce|vc|seu|sua)\b', value) and duplicates > 1: flags.append('HARASSMENT_POSSIBLE')
            if recent and recent[-1][3] and value in {'ruim nisso', 'burro', 'idiota'}:
                flags.append('REVIEW')
            laughter = bool(re.fullmatch(r'(?:k+|ha+|he+|rs)+[!. ]*', value))
            if not laughter and re.search(r'(.)\1{' + str(c.repeated_chars-1) + r',}', value): flags.append('SPAM')
            if sum(unicodedata.category(char) == 'So' for char in text) >= c.emoji_threshold: flags.append('REVIEW')
            if not flags: flags = ['SAFE'] if value else ['UNKNOWN']
            severity = 'HIGH' if 'SUSPICIOUS_LINK' in flags and (link_count >= c.high_link_threshold or 'FLOOD' in flags) else 'MEDIUM' if any(f in flags for f in ('FLOOD','DUPLICATE','SPAM','HARASSMENT_POSSIBLE')) else c.promotion_severity if promotion else 'LOW'
            order = ('SUSPICIOUS_LINK','FLOOD','SPAM','HARASSMENT_POSSIBLE','OFFENSIVE_POSSIBLE','DUPLICATE','SELF_PROMOTION','REVIEW','UNKNOWN','SAFE')
            category = next(f for f in order if f in flags)
            suppress = any(f in flags for f in ('FLOOD','SPAM')) or duplicates >= max(3,c.duplicate_threshold) or severity == 'HIGH'
            result = ModerationResult(category,severity,tuple(flags),fingerprint,suppress,not suppress and (flags == ['SAFE'] or flags == ['DUPLICATE']))
            rows.append((now,fingerprint,links,bool(re.fullmatch(r'(?:voce|vc) e (?:muito|tao)\.{0,3}', value))))
            self.recent_messages_by_author.move_to_end(author)
            while len(self.recent_messages_by_author)>c.max_authors: self.recent_messages_by_author.popitem(last=False)
            self.counts['MOD_MESSAGES_ANALYZED'] += 1
            for flag in flags: self.counts['MOD_'+flag] += 1
            if severity == 'HIGH': self.counts['MOD_HIGH_ALERTS'] += 1
            if category != 'SAFE':
                self.serial += 1
                row = dict(id=str(self.serial),author=author,excerpt=text[:c.excerpt_chars],category=category,severity=severity,at=now,time=time.strftime('%H:%M:%S'),fingerprint=fingerprint)
                self.moderation_queue[row['id']] = row; self.last_alert = row
                while len(self.moderation_queue)>c.max_reviews: self.moderation_queue.popitem(last=False)
            return result

    def review(self, ident, action):
        with self.lock:
            self._expire()
            if action not in {'OK','IGNORE','KEEP'}: return False
            if ident not in self.moderation_queue: return False
            if action != 'KEEP': self.moderation_queue.pop(ident)
            if action == 'OK': self.counts['MOD_FALSE_POSITIVE_CLEARED'] += 1
            return True

    def snapshot(self):
        with self.lock:
            self._expire()
            return {**self.counts,'MOD_REVIEW_QUEUE':len(self.moderation_queue),'MOD_LAST_ALERT': (' / '.join(self.last_alert[k] for k in ('category','author','severity')) if self.last_alert else '—')}

    def reviews(self):
        with self.lock:
            self._expire()
            return [dict(row) for row in self.moderation_queue.values()]
