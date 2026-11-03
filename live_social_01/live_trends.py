"""Small, bounded RAM-only registry of collective public questions."""
import re
import time
import uuid
import unicodedata
from collections import Counter, deque
from threading import RLock


def signature(text):
    norm = unicodedata.normalize('NFKD', text.casefold())
    words = set(re.findall(r'[a-z0-9]+', ''.join(c for c in norm if not unicodedata.combining(c))))
    entity = next((x for x in ('celular', 'python', 'robo', 'jarvis') if x in words), '')
    creation = bool(words & {'criou', 'criado', 'fez', 'feito', 'desenvolveu', 'desenvolvido', 'comecou'})
    if creation and words & {'jarvis', 'projeto', 'ele'} and entity in {'', 'jarvis'}:
        return 'criacao', 'jarvis', {'criacao', 'jarvis'}
    if words & {'linguagem', 'python'} and words & {'usa', 'feito', 'linguagem'}:
        return 'linguagem', entity or 'jarvis', {'linguagem', 'implementacao'}
    intent = 'funcionamento' if words & {'funciona', 'funcionar'} else 'recomendacao' if words & {'recomenda', 'melhor'} else 'pergunta'
    return intent, entity, words - {'como', 'voce', 'ele', 'ela', 'o', 'a', 'de', 'do', 'no', 'que', 'qual', 'e', 'esse', 'essa'}


class TrendClusters:
    def __init__(self, clock=time.monotonic, threshold=3):
        self.clock, self.threshold = clock, threshold
        self.groups, self.counts, self.logs = [], Counter({name: 0 for name in (
            'TREND_CLUSTERS_CREATED', 'TREND_CLUSTERS_TRENDING', 'TREND_MESSAGES_AGGREGATED',
            'TREND_UNIQUE_AUTHORS', 'TREND_COLLECTIVE_ADDRESSED', 'TREND_REPEAT_BLOCKED')}), deque(maxlen=100)
        self.lock = RLock()

    def _log(self, name, cluster):
        self.logs.append(f'{name} | cluster={cluster["trend_cluster_id"]} | authors={cluster["unique_authors"]}')

    def observe(self, author, text):
        with self.lock:
            now = self.clock()
            self.groups[:] = [g for g in self.groups if now-g['last_seen'] < (300 if g['status'] == 'FORMING' else 14400)]
            intent, entity, tokens = signature(text)
            group = None
            for g in reversed(self.groups):
                overlap = len(tokens & g['tokens']) / max(1, len(tokens | g['tokens']))
                if intent == g['intent'] and not (entity and g['entity'] and entity != g['entity']) and overlap >= .55:
                    group = g
                    break
            if group is None:
                group = dict(trend_cluster_id=uuid.uuid4().hex, unique_authors=0, message_count=0,
                             representative_question=text[:500], first_seen=now, last_seen=now,
                             status='FORMING', authors=set(), tokens=tokens, intent=intent, entity=entity,
                             claimed=False, answer='', addressed_at=None, addressed_authors=set())
                if len(self.groups) >= 64: self.groups.pop(0)
                self.groups.append(group)
                self.counts['TREND_CLUSTERS_CREATED'] += 1
                self._log('TREND_CLUSTER_CREATED', group)
            joined = group['message_count'] > 0
            group['message_count'] += 1
            # Bound participants as well as clusters; only opaque author identifiers in RAM.
            if len(group['authors']) < 200: group['authors'].add(author)
            group['unique_authors'] = len(group['authors'])
            group['last_seen'] = now
            if joined:
                self.counts['TREND_MESSAGES_AGGREGATED'] += 1
                self._log('TREND_CLUSTER_JOIN', group)
            if group['addressed_at'] is not None:
                group['status'] = 'COOLDOWN'
                evolved = len(group['authors'] - group['addressed_authors']) >= self.threshold
                if now-group['addressed_at'] >= 300 and evolved:
                    group['status'], group['claimed'] = 'FORMING', False
                elif joined:
                    self.counts['TREND_REPEAT_BLOCKED'] += 1
                    self._log('TREND_CLUSTER_REPEAT_BLOCKED', group)
            if group['status'] == 'FORMING' and group['unique_authors'] >= self.threshold:
                group['status'] = 'TRENDING'
                self.counts['TREND_CLUSTERS_TRENDING'] += 1
                self._log('TREND_CLUSTER_PROMOTED', group)
            self.counts['TREND_UNIQUE_AUTHORS'] = len(set().union(*(g['authors'] for g in self.groups)))
            return group, joined

    def opportunity(self):
        with self.lock:
            for g in self.groups:
                if g['status'] == 'TRENDING' and g['claimed'] and self.clock()-g.get('claimed_at', self.clock()) >= 45:
                    g['claimed'] = False
            return next((g for g in self.groups if g['status'] == 'TRENDING' and not g['claimed']
                         and self.clock()-g['last_seen'] < 300), None)

    def answered(self, text, answer):
        intent, entity, tokens = signature(text)
        with self.lock:
            for g in self.groups:
                if g['intent'] == intent and g['entity'] == entity and g['tokens'] == tokens:
                    g['answer'] = answer[:1200]

    def addressed(self, ident):
        with self.lock:
            g = next((g for g in self.groups if g['trend_cluster_id'] == ident), None)
            if not g or g['status'] != 'TRENDING': return
            g.update(TREND_COLLECTIVE_ADDRESSED=True, status='ADDRESSED', addressed_at=self.clock(), addressed_authors=set(g['authors']), claimed=True)
            self.counts['TREND_COLLECTIVE_ADDRESSED'] += 1
            self._log('TREND_CLUSTER_ADDRESSED', g)

    def drain_logs(self):
        with self.lock:
            result = list(self.logs)
            self.logs.clear()
            return result

    def snapshot(self):
        with self.lock:
            return {**self.counts, 'TREND_OPPORTUNITY': self.opportunity()}
