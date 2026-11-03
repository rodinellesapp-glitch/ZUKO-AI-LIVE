"""Offline TikTok fixtures through the SAME monitor/Flow/Director/Writer queue.

All speech and Gemini calls are mocks. No Studio control or external connection.
"""
import json
import time
from collections import deque
from types import SimpleNamespace as NS
from unittest.mock import patch
from live_tiktok_source import TikTokSimulatorSource
from live_tiktok_adapter import TikTokLiveAdapter
from simulate_live_flow_4 import build_monitor


def chat(ident, author, text):
    return dict(event_type='CHAT_MESSAGE',event_id=str(ident),author_id=author,
                author_name=author,text=text)


def simulate(rows, seconds=40, mode='MISTO', capabilities=None, offline_at=None):
    # A mistaken external call is a test failure, never a spent API request.
    with patch('requests.sessions.Session.request',side_effect=AssertionError('Offline simulator: HTTP forbidden')), \
         patch('socket.create_connection',side_effect=AssertionError('Offline simulator: network forbidden')), \
         patch('live_response.GeminiResponder.generate',side_effect=AssertionError('Offline simulator: real Gemini forbidden')):
        return _simulate(rows,seconds,mode,capabilities,offline_at)


def _simulate(rows, seconds, mode, capabilities, offline_at):
    now=[1000.]; clock=lambda:now[0]
    monitor=build_monitor(clock)
    monitor.source='tiktok-sim'
    monitor._tiktok_mock_tts=True  # The existing simulator owns the mocked voice.
    monitor.tiktok_source=TikTokSimulatorSource(capabilities)
    monitor.tiktok_source.start()
    monitor.tiktok_adapter=TikTokLiveAdapter(monitor.tiktok_source,clock)
    monitor.writer.set_mode(mode)
    pending=deque(sorted(rows,key=lambda row:row[0]))
    with patch('live_monitor.time', NS(monotonic=clock,perf_counter=clock,strftime=time.strftime)):
        for step in range((seconds+180)*2):
            tick=step*.5;now[0]=1000.+tick
            if offline_at is not None and tick==offline_at: monitor.tiktok_source.stop()
            while pending and pending[0][0]<=tick:
                _,raw=pending.popleft();monitor.tiktok_source.push(raw)
            monitor._tiktok_capture()
            for author,entry in list(monitor.bursts._pending.items()):
                monitor.bursts._flush(author,entry['version'])
            if tick<seconds: monitor._presenter_tick()
            else: monitor._flow_tick()
            monitor.director.run_once();monitor.voice.tick(monitor)
            if tick>=seconds and not pending and not monitor.flow.batches and not monitor.voice.pending and not monitor.voice.active and not monitor.director.pending_units: break
    monitor.bursts.stop()
    speech=[response for _,response in monitor.voice.spoken]
    counts=monitor.tiktok_adapter.counts
    metrics=dict(events_received=counts['TIKTOK_EVENTS_RECEIVED'],
        events_normalized=counts['TIKTOK_EVENTS_NORMALIZED'],speech_selected=len(speech),
        gemini_calls=monitor.mock_calls,local_speech=sum(r.provider!='GEMINI' for r in speech),
        ignored=monitor.flow.counts['ignored'],registered_only=monitor.flow.counts['registered_only'],
        max_tts_queue=monitor.voice.max_queue,gift_batches=monitor.flow.counts['gift_batches'],
        pace_transitions=[pace for _,pace in monitor.flow.transitions],
        max_words=max((len(r.text.split()) for r in speech),default=0),
        real_gemini_calls=monitor.generator.gemini.calls_made,
        real_ollama_calls=0,real_youtube_calls=0,real_tiktok_calls=0,tools=0)
    return dict(metrics=metrics,monitor=monitor,speech=speech)


def scenarios():
    rows=[(i,chat(i,a,t)) for i,(a,t) in enumerate((('Ana','oi'),('João','Jarvis conta uma piada'),
        ('Carlos','😂😂😂'),('Maria','qual seu carro favorito?'),('Pedro','67')))]
    kinds=('CHAT_MESSAGE','VIEWER_JOIN','LIKE_EVENT','FOLLOW','CHAT_MESSAGE')
    hundred=[]
    for i in range(100):
        kind=kinds[i%5]
        raw=chat(i,'Autor'+str(i),'😂' if i%5==4 else 'papo leve sobre o dia a dia')
        raw['event_type']=kind
        if kind!='CHAT_MESSAGE':raw.pop('text')
        hundred.append((i*.3,raw))
    gifts=[(i*.5,dict(event_type='GIFT_EVENT',event_id='gift'+str(i),author_id=a,
        author_name=a,gift_type=g,gift_quantity=n,high=h)) for i,(a,g,n,h) in enumerate(
            (('Ana','Rosa',1,False),('João','Rosa',2,False),('Carlos','Rosa',1,False),('Maria','HIGH',1,True)))]
    return {'chat':dict(rows=rows,mode='GEMINI+'), '100_events':dict(rows=hundred),
        'hyper':dict(rows=[(i*.6,chat(i,'Autor'+str(i),'Como começar essa ideia?' if i%10==0 else 'papo leve')) for i in range(50)]),
        'gifts':dict(rows=gifts,seconds=15),
        'offline':dict(rows=[],seconds=120,offline_at=10)}


def report(): return {name:simulate(**args)['metrics'] for name,args in scenarios().items()}

if __name__=='__main__': print(json.dumps(report(),ensure_ascii=False,indent=2))
