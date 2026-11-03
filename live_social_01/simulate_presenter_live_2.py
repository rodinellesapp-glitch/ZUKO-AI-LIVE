"""Accelerated deterministic offline exercise; no devices, clients or network."""
import random
from collections import Counter, deque
from live_audience import LiveAudienceManager
from live_director import DirectorUnit, LiveDirectorManager
from live_events import LiveEventEngine
from live_moderator import LiveModeratorManager
from live_presenter import LivePresenterManager, AUTO
from live_session_memory import LiveSessionMemory
from youtube_dom_chat import YouTubeDomChat


def simulate(seconds=3600, mixed=True, seed=42, profile=None):
    rng=random.Random(seed); now=[1000.0]; clock=lambda:now[0]
    memory=LiveSessionMemory(clock=clock)
    presenter=LivePresenterManager(clock=clock,session_memory=memory); presenter.mode=AUTO
    if profile:presenter.engagement.configure_live(**profile)
    audience=LiveAudienceManager(clock=clock,session_memory=memory)
    moderator=LiveModeratorManager(clock=clock)
    events=LiveEventEngine(clock=clock); dom=YouTubeDomChat()
    pending=deque(); active=[None]; end=[0.0]; counts=Counter()
    spoken=[]; high_received=set(); high_spoken=set(); max_queue=0; max_tts=0
    modes={'CALM'}
    def tts():
        return {'TTS_STATE':'PLAYING' if active[0] else 'IDLE','TTS_QUEUE_DEPTH':len(pending)}
    def dispatch(unit):
        counts['generation_active']+=1
        counts['max_generation']=max(counts['max_generation'],counts['generation_active'])
        # Fixed response is a stand-in for the model/voice, not a real call.
        if director.before_tts(unit.unit_id):
            pending.append((unit.unit_id,unit.source,unit.metadata.get('engagement_action'),unit.content_ref))
            director.tts_queued(unit.unit_id)
        counts['generation_active']-=1
    director=LiveDirectorManager(dispatch,tts,clock=clock)
    quiet_actions=[]
    for tick in range(seconds+121):
        now[0]=1000.0+tick
        if active[0] and now[0]>=end[0]:
            ident,source,action,_=active[0]; active[0]=None
            spoken.append((now[0],source))
            if source=='HIGH_EVENT':high_spoken.add(ident)
            if action:
                presenter.engagement.commit(action); quiet_actions.append((now[0],action))
            presenter.engagement.spoken()
        rate=(0,14,30,60)[min(3,tick//900)] if mixed and tick<seconds else 0
        if mixed and tick<seconds:
            # Deterministic events, not a platform connection.
            if tick and tick%97==0:
                kind=rng.choice(('GIFT','MEMBER','SUPER_CHAT'))
                event,state=events.accept({'event_id':f'event-{tick}','type':kind,'author':'Simulado','amount':'R$ 5'})
                if event and state=='accepted':
                    presenter.engagement.activity(kind)
                    high_received.add(event.event_id)
                    director.submit(DirectorUnit(event.event_id,'HIGH_EVENT','Simulado',event_type=kind,
                        created_at=clock(),content_ref=events.rule_reply(event)))
            interval=max(1,60//rate) if rate else 0
            if interval and tick%interval==0:
                ident=f'm-{tick}'; author=f'Autor-{rng.randrange(20)}'
                text=rng.choice(('Como funciona sua memória?', 'Como aprender Python?', 'Olá', '❤️🔥',
                    'Como criou o Jarvis?', 'Como começou a desenvolver esse Jarvis?', 'https://spam.invalid oferta'))
                dom.ingest({'message_id':ident,'author':author,'text':text})
                for comment in dom.drain():
                    counts['dom']+=1
                    decision=moderator.analyze(comment.author,comment.text)
                    if not decision.presenter_allowed:
                        counts['moderated']+=1; continue
                    from live_reactions import reaction_only
                    presenter.observe_safe(comment.comment_id,comment.author,comment.text,not reaction_only(comment.text))
                    choice,candidate=audience.admit(comment.comment_id,comment.author,comment.text,moderation=decision)
                    modes.add(audience.metrics['AUDIENCE_MODE'])
                    if choice=='SELECT':
                        counts['selected']+=1
                        version=director.conversation_arrived(comment.author)
                        director.submit(DirectorUnit(comment.comment_id,'AUDIENCE',comment.author,
                            classification=candidate.classification,created_at=clock(),conversation_version=version,
                            content_ref='Resposta simulada à pergunta atual.'))
                    else:counts['silenced']+=1
        # Pending presentation obsolete after chat/events does not wait for a lease timeout.
        if presenter.engagement.pending is not None and not active[0] and not pending and not director.pending_units:
            presenter.engagement.pending=None
        suggestion=presenter.evaluate_live(audience.metrics,tts(),director.snapshot()) if tick<seconds else None
        if suggestion:
            approved=presenter.approve()
            if approved:
                ident=f'p-{tick}'
                director.submit(DirectorUnit(ident,'TRENDING' if approved.cluster else 'PRESENTER','JARVIS',
                    classification='TRENDING' if approved.cluster else 'ENGAGEMENT' if not approved.engagement.sustain else 'CHAT',
                    created_at=clock(),content_ref=approved.text,
                    metadata={'engagement_action':approved.engagement,'cluster':approved.cluster}))
                if approved.cluster:memory.trends.addressed(approved.cluster['trend_cluster_id'])
        director.run_once()
        if not active[0]:
            while pending:
                item=pending.popleft()
                if not director.allow_playback(item[0]):
                    counts['stale_audio']+=1; continue
                active[0]=item; end[0]=clock()+12; break
        max_queue=max(max_queue,len(director.pending_units)); max_tts=max(max_tts,len(pending))
        if tick>=seconds and not active[0] and not pending and not director.pending_units:break
    return {'counts':dict(counts),'actions':quiet_actions,'spoken':spoken,
        'high_received':high_received,'high_spoken':high_spoken,'max_director_queue':max_queue,
        'max_tts_queue':max_tts,'modes':modes,'presenter':presenter,'memory':memory,'director':director}


if __name__=='__main__':
    import json
    result=simulate()
    print(json.dumps({key:result[key] for key in ('counts','max_director_queue','max_tts_queue')},ensure_ascii=False))
    print('HIGH received/delivered:',len(result['high_received']),len(result['high_spoken']))
    print('Presenter speeches:',len(result['actions']))
