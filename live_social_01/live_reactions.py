"""Local emoji evidence, not a spectator profile or platform gift detector."""
import time
from threading import RLock
from functools import wraps
from collections import Counter, OrderedDict, deque

EMOJIS = {'LOVE': ('❤','♥','💙','💚','💜','😍'), 'LIKE': ('👍',), 'STRONG_APPROVAL':('💯',),
          'FLOWER': ('🌹','🌸'), 'LAUGH': ('😂','🤣'), 'HYPE': ('🔥',),
          'APPLAUSE': ('👏',), 'SURPRISE': ('😮','🤯'), 'SAD_REACTION': ('😢','😭'),
          'THINKING':('🤔',),'WATCHING':('👀',),'CELEBRATION': ('🎉','🥳')}


def reaction_details(text):
    remainder=text
    counts={kind:sum(text.count(emoji) for emoji in emojis) for kind,emojis in EMOJIS.items()}
    for emojis in EMOJIS.values():
        for emoji in emojis:remainder=remainder.replace(emoji,'')
    plain=remainder.strip(' \n\t!?.,;:\ufe0f\u200d')
    negative=bool(__import__('re').search(r'\b(horr[ií]vel|ruim|p[eé]ssima|terr[ií]vel|n[aã]o gostei)\b',plain.casefold()))
    positive=bool(__import__('re').search(r'\b(boa|bom|gostei|adorei|massa|legal|kk+|ha+|rs+)\b',plain.casefold()))
    return {'categories':[k for k,v in counts.items() if v],'emoji_count':sum(counts.values()),
        'counts':counts,'text_present':bool(plain),'text_intent':'MIXED_HUMOR' if negative and counts['LAUGH'] else 'NEGATIVE_REACTION' if negative else 'POSITIVE_REACTION' if positive else 'NEUTRAL'}


def categories(text):
    return [kind for kind, emojis in EMOJIS.items() if any(emoji in text for emoji in emojis)]


def reaction_only(text):
    remainder = text
    for emojis in EMOJIS.values():
        for emoji in emojis: remainder = remainder.replace(emoji, '')
    return bool(categories(text)) and not remainder.strip(' \n\t!?.,;:\ufe0f\u200d')


def reaction_comment(text):
    """Evaluations of the last content are feedback, not a question to answer."""
    details=reaction_details(text)
    return reaction_only(text) or (details['emoji_count']>0 and '?' not in text
        and details['text_intent'] in {'MIXED_HUMOR','NEGATIVE_REACTION','POSITIVE_REACTION'}
        and not __import__('re').search(r'\b(como|qual|porque|por qu[eê]|me explica|recomenda)\b',text.casefold()))


def synchronized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock: return method(self,*args,**kwargs)
    return call


class LiveReactionEngine:
    def __init__(self, clock=time.monotonic, window=15, cooldown=45, threshold=3):
        self.lock=RLock()
        self.clock, self.window, self.cooldown, self.threshold = clock, window, cooldown, threshold
        self.records, self.seen, self.counts = deque(maxlen=300), OrderedDict(), Counter()
        self.last_collective, self.mood = float('-inf'), 'QUIET'
        self.logs = deque(maxlen=100)
        self.details=OrderedDict();self.last_details={}

    @synchronized
    def reset(self):
        self.records.clear(); self.seen.clear(); self.counts.clear(); self.logs.clear()
        self.last_collective, self.mood = float('-inf'), 'QUIET'
        self.details.clear();self.last_details={}

    @synchronized
    def observe(self, ident, author, text):
        if ident in self.seen: return False
        kinds = categories(text)
        if not kinds: return False
        self.seen[ident] = None
        while len(self.seen)>1000: self.seen.popitem(last=False)
        self.records.append((self.clock(), author, tuple(kinds)))
        details=reaction_details(text)
        self.last_details={**details,'author':author,'correlation_id':ident}
        self.details[ident]={**self.last_details,'at':self.clock()}
        while len(self.details)>300:self.details.popitem(last=False)
        self.counts['REACTION_EMOJIS']+=details['emoji_count']
        self.counts['REACTION_DETECTED'] += 1
        self.counts['REACTION_AGGREGATED'] += 1
        self.logs.append('REACTION_DETECTED | category=' + ','.join(kinds)+
            f' | emoji_count={details["emoji_count"]} | author={author[:128]} | text_present={details["text_present"]} | correlation_id={ident[:256]}')
        self.logs.append('REACTION_AGGREGATED | correlation_id='+ident[:256])
        return True

    @synchronized
    def groups(self):
        now = self.clock()
        for ident in list(self.details):
            if now-self.details[ident]['at']>self.window:del self.details[ident]
        while self.records and now-self.records[0][0]>self.window: self.records.popleft()
        groups = {}
        for stamp, author, kinds in self.records:
            for kind in kinds:
                g = groups.setdefault(kind, dict(reaction_type=kind, message_count=0, authors=set(), first_seen=stamp, last_seen=stamp))
                g['message_count'] += 1; g['authors'].add(author); g['last_seen'] = stamp
        for g in groups.values(): g['unique_authors']=len(g['authors'])
        return groups

    @synchronized
    def opportunity(self):
        if self.clock()-self.last_collective<self.cooldown: return None
        eligible = [g for g in self.groups().values() if g['unique_authors']>=self.threshold]
        return max(eligible,key=lambda g:g['unique_authors']) if eligible else None

    @synchronized
    def addressed(self):
        self.last_collective = self.clock()
        self.counts['REACTION_COLLECTIVE_TRIGGER'] += 1
        self.logs.append('REACTION_COLLECTIVE_TRIGGER')

    @synchronized
    def snapshot(self, idle=0, chat_rate=0):
        groups = self.groups()
        authors = set().union(*(g['authors'] for g in groups.values()))
        mood = ('SOMBER' if groups.get('SAD_REACTION',{}).get('unique_authors',0)>=3 else 'HYPED' if any(g['unique_authors']>=3 for k,g in groups.items() if k in {'HYPE','LOVE','APPLAUSE'})
                else 'ENGAGED' if len(authors)>=3 or chat_rate>=8 else 'QUIET' if idle>=15 or not chat_rate else 'NEUTRAL')
        if mood!=self.mood:
            self.logs.append(f'AUDIENCE_MOOD_CHANGED | {mood}'); self.counts['AUDIENCE_MOOD_CHANGED']+=1
        self.mood=mood
        return {**self.counts,'AUDIENCE_MOOD':mood,'REACTION_ACTIVE':','.join(groups) or '—',
                'REACTION_UNIQUE_AUTHORS':len(authors)}

    @synchronized
    def drain_logs(self):
        result=list(self.logs); self.logs.clear(); return result
