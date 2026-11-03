"""Offline combined scenario. Dispatch records identifiers, never invokes AI/audio."""
from live_director import DirectorUnit, LiveDirectorManager
from live_moderator import LiveModeratorManager
from live_audience import LiveAudienceManager
from live_events import LiveEventEngine


def simulate():
    now = lambda: 100.0
    order = []
    director = LiveDirectorManager(lambda unit: order.append(unit.unit_id), clock=now)
    moderator = LiveModeratorManager(clock=now)
    audience = LiveAudienceManager(clock=now)
    events = LiveEventEngine(clock=now)
    director.submit(DirectorUnit('presenter', 'PRESENTER', 'JARVIS', created_at=100))
    for ident, author, text in [('ana', '@ANA', 'Como estudar astronomia?'),
                                ('spam', '@BRUNO', 'https://spam.example https://spam.example')]:
        result = moderator.analyze(author, text)
        decision, item = audience.admit(ident, author, text, moderation=result)
        if decision == 'SELECT':
            director.submit(DirectorUnit(ident, 'AUDIENCE', author,
                classification=item.classification, created_at=100))
    event, _ = events.accept({'event_id':'carlos', 'type':'SUPER_CHAT', 'author':'@CARLOS', 'message':'Como funciona o JARVIS?'})
    director.submit(DirectorUnit(event.event_id, 'HIGH_EVENT', event.author_name,
        event_type=event.event_type, requires_ai=True, created_at=100))
    # Already classified trend supplied by the audience layer; no classification in Director.
    director.submit(DirectorUnit('trending', 'AUDIENCE', 'grupo', classification='TRENDING', created_at=100))
    while director.run_once(): pass
    return {'order': order, 'history': list(director.history), 'metrics': director.snapshot(),
            'moderation': moderator.snapshot(), 'real_calls': 0}


if __name__ == '__main__':
    print(simulate())
