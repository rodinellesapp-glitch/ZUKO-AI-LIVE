import time
import uuid
from vendor.nexus.live_tiktok_source import TikTokSimulatorSource
from vendor.nexus.live_tiktok_adapter import TikTokLiveAdapter


def simulated(kind, user='Teste', text='Oi NPC!', gift='Rosa'):
    source = TikTokSimulatorSource()
    source.start()
    source.push({'event_type':kind, 'event_id':uuid.uuid4().hex, 'author_name':user,
                 'author_id':user, 'text':text if kind == 'CHAT_MESSAGE' else None,
                 'gift_type':gift if kind == 'GIFT_EVENT' else None,
                 'gift_quantity':1 if kind == 'GIFT_EVENT' else None, 'timestamp':time.time()})
    event = TikTokLiveAdapter(source).read_event()
    source.stop()
    if event is None:
        raise ValueError('Evento simulado rejeitado pelo adaptador NEXUS.')
    return event


def real_source(channel):
    # Nenhuma segunda implementação de TikTok: usa a cópia do conector existente.
    from vendor.nexus.live_tiktok_real_source import TikTokRealEventSource
    source = TikTokRealEventSource(channel)
    return source, TikTokLiveAdapter(source)
