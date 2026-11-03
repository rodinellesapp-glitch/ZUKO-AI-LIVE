"""Accelerated internal TikTok contract simulation through the real LiveMonitor methods."""
import json
import math
from collections import Counter, deque
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from live_monitor import LiveMonitor
from live_audience import LiveAudienceManager
from live_moderator import LiveModeratorManager
from live_presenter import LivePresenterManager, AUTO
from live_session_memory import LiveSessionMemory
from live_events import LiveEventEngine
from live_response import LiveResponseGenerator
from live_director import LiveDirectorManager
from live_telemetry import LiveTelemetry
from live_burst import BurstCoordinator
from live_platform_adapter import TikTokContractAdapter
import threading
import time

class SimulatedVoice:
    def __init__(self,clock):self.clock=clock;self.pending=deque();self.active=None;self.end=0.;self.max_queue=0;self.spoken=[]
    def snapshot(self):return {'TTS_STATE':'PLAYING' if self.active else 'IDLE','TTS_QUEUE_DEPTH':len(self.pending)}
    def enqueue(self,response):
        self.pending.append(response);self.max_queue=max(self.max_queue,len(self.pending))
    def tick(self,m):
        if self.active and self.clock()>=self.end:
            r=self.active;self.active=None;self.spoken.append((self.clock(),r));m._spoken(r,0)
            m._log('TTS_OK')
        if not self.active:
            while self.pending:
                r=self.pending.popleft()
                if not m.director.allow_playback(r.comment_id):continue
                if not r.tts_enabled:
                    m._tts_event('TTS_SKIPPED',r)
                    continue
                self.active=r;self.end=self.clock()+max(2,math.ceil(len(r.text.split())/3));m._audio_started(r,0)
                m._log('TTS_INICIO');break

def build_monitor(clock):
    m=LiveMonitor.__new__(LiveMonitor)
    m.reading=True;m.paused=False;m.local_test_mode=False;m.session_epoch=0;m.state='WATCHING'
    m.root=Mock();m.dashboard=Mock();m.telemetry=LiveTelemetry();m.metrics=[];m.logs=deque(maxlen=2000)
    m._log=lambda value:m.logs.append(value);m.set_state=lambda value:setattr(m,'state',value);m._publish_live=Mock()
    m.generator=LiveResponseGenerator();m.generator.conversation_state._clock=clock
    m.session_memory=LiveSessionMemory(clock=clock)
    m.audience=LiveAudienceManager(clock=clock,session_memory=m.session_memory)
    m.moderator=LiveModeratorManager(clock=clock)
    m.presenter=LivePresenterManager(clock=clock,session_memory=m.session_memory);m.presenter.mode=AUTO
    m._init_live_flow(clock);m.events=LiveEventEngine(clock=clock);m.voice=SimulatedVoice(clock)
    m.gemini_lock=threading.Lock();m._engagement_pending={};m.gemini_cooldown_notice_until=0.
    m.generator.gemini.last_output_category='OK';m.generator.gemini.last_timings={};m.generator.gemini.last_context_metrics={}
    m.generator.gemini.last_finish_reason='STOP';m.generator.gemini.last_output_chars=0
    m.mock_calls=0
    def writer(text,*args):
        m.mock_calls+=1
        if 'Redija somente' in text:return 'Cena fictícia: dois amigos discutem o melhor caminho e percebem que começar com uma ideia simples já muda o papo.'
        hint=args[-1] if args else ''
        if 'PLAY_ALONG' in hint:return 'Batman no chat? Então hoje a missão é salvar a conversa do silêncio, sem precisar de capa!'
        if 'carros' in text.lower():return 'Conforto e uso diário ajudam nessa escolha. Vale comparar espaço, consumo e manutenção sem decidir só pela aparência.'
        beginnings=('Uma ideia simples pode ser um bom começo.','Dá para começar pelo objetivo.','Esse ponto merece um pouco de calma.',
            'Eu iria pelo caminho mais simples.','Tem mais de um jeito de olhar para isso.')
        endings=('Comparar os caminhos ajuda a decidir.','Sem transformar o papo numa disputa.','Um exemplo claro já ajuda bastante.',
            'Vale deixar espaço para outras opiniões.','Leveza também faz parte de uma boa conversa.')
        i=m.mock_calls-1
        return beginnings[i%5]+' '+endings[(i//5)%5]
    m.generator.gemini.generate=Mock(side_effect=writer)
    m.director=LiveDirectorManager(m._dispatch_director,m.voice.snapshot,clock=clock)
    m.bursts=BurstCoordinator(m._submit_director_comment,window=100,on_event=m._log)
    return m

def scenario_100():
    rows=[]
    def add(kind,n,text='',**extra):
        for _ in range(n):
            i=len(rows);rows.append((i*1.2,dict(event_id='e'+str(i),event_type=kind,
                author_id='Autor'+str(i),author_name='Ana' if i%2 else 'Carlos',text=text,**extra)))
    add('CHAT_MESSAGE',30,'papo leve sobre o dia a dia')
    add('VIEWER_JOIN',20)
    add('LIKE_EVENT',15)
    add('CHAT_MESSAGE',10,'😂')
    add('GIFT_EVENT',10,gift_type='Rosa',gift_quantity=1)
    add('CHAT_MESSAGE',5,'Como escolher um caminho interessante?')
    add('FOLLOW',5)
    add('SHARE_EVENT',3)
    add('GIFT_EVENT',2,gift_type='Especial',gift_quantity=1,high=True)
    return rows

def simulate(rows=None,seconds=180,theme=None,host_controls=()):
    rows=scenario_100() if rows is None else rows
    now=[1000.];clock=lambda:now[0];m=build_monitor(clock)
    if theme:m.presenter.engagement.configure_live(theme=theme)
    adapter=TikTokContractAdapter();events=deque(sorted(rows,key=lambda row:row[0]));controls=deque(host_controls)
    high_received=set();high_delivered=set();max_director=0
    with patch('live_monitor.time',NS(monotonic=clock,perf_counter=clock,strftime=time.strftime)):
        for tick in range(seconds+180):
            now[0]=1000.+tick
            while controls and controls[0][0]<=tick:
                _,command=controls.popleft();m.submit_local_text(command)
            while events and events[0][0]<=tick:
                _,raw=events.popleft();event=adapter.normalize(raw,verified=True)
                if event.priority=='HIGH':high_received.add('flow-high:'+event.event_id)
                m.accept_platform_event(event)
            for author,entry in list(m.bursts._pending.items()):m.bursts._flush(author,entry['version'])
            # Stop spontaneous presentation at scenario end, then drain selected work.
            if tick<seconds:m._presenter_tick()
            else:m._flow_tick()
            m.director.run_once();m.voice.tick(m)
            max_director=max(max_director,len(m.director.pending_units))
            if tick>=seconds and not events and not m.flow.batches and not m.voice.active and not m.voice.pending and not m.director.pending_units:break
        m.bursts.stop()
    speech=[r for _,r in m.voice.spoken];words=[len(r.text.split()) for r in speech]
    for r in speech:
        if r.comment_id.startswith('flow-high:'):high_delivered.add(r.comment_id)
    presenter_actions=[a for a in m.presenter.engagement.producer.actions]
    metrics={'total_events':m.flow.counts['total_events'],'spoken_responses':len(speech),
        'ignored':m.flow.counts['ignored'],'registered_only':m.flow.counts['registered_only'],'batched':m.flow.counts['batched'],
        'average_words':round(sum(words)/max(1,len(words)),1),'max_words':max(words,default=0),
        'questions_percent':round(100*sum('?' in r.text for r in speech)/max(1,len(speech)),1),
        'gift_batches':m.flow.counts['gift_batches'],'reaction_batches':m.presenter.engagement.reactions.counts['REACTION_COLLECTIVE_TRIGGER'],
        'max_tts_queue':m.voice.max_queue,'max_director_queue':max_director,
        'high_events_received':len(high_received),'high_events_delivered':len(high_delivered),
        'gemini_mock_calls':m.mock_calls,'duplicate_phrases':len(speech)-len({r.text for r in speech}),
        'pace_transitions':[p for _,p in m.flow.transitions],
        'spontaneous_invites_percent':round(100*sum(a['invites'] for a in presenter_actions)/max(1,len(presenter_actions)),1)}
    return {'metrics':metrics,'monitor':m,'speech':speech}

def simulation_report():
    def chat(i,text,author='Ana'):
        return dict(event_type='CHAT_MESSAGE',event_id=str(i),author_id=author,author_name=author,text=text)
    def gift(i,author,n=1,high=False):
        return dict(event_type='GIFT_EVENT',event_id=str(i),author_id=author,author_name=author,gift_type='Rosa',gift_quantity=n,high=high)
    scenarios={
        '100_events':{},
        'fast_50':dict(rows=[(i*.6,chat(i,'Como começar essa ideia?' if i%10==0 else 'qualquer coisa','Autor'+str(i))) for i in range(50)],seconds=40),
        'gifts':dict(rows=[(0,gift('g1','Ana')),(.5,gift('g2','João')),(1,gift('g3','Carlos',2)),(1.5,gift('high','Maria',1,True))],seconds=15),
        'greetings':dict(rows=[(0,chat(i,'oi','Autor'+str(i))) for i in range(10)],seconds=10),
        'humor':dict(rows=[(0,chat('humor','sou um Batman perdido no chat'))],seconds=10),
        'unknown_67':dict(rows=[(0,chat('unknown','67'))],seconds=10),
        'emoji':dict(rows=[(20+i*.2,chat(i,text,'Autor'+str(i))) for i,text in enumerate(('😂','😂😂','🤣','essa foi péssima 😂','👏'))],seconds=40),
        'chat_gift':dict(rows=[(0,chat('q','Como começar?'))]+[(1+i*.2,gift('gift'+str(i),'Autor'+str(i))) for i in range(3)],seconds=20),
        'takeover_5min':dict(rows=[],seconds=330,host_controls=((0,'Jarvis, segura um pouco.'),(300,'Voltei.'))),
        'general_60min':dict(rows=[],seconds=3600),
        'cars_20min':dict(rows=[],seconds=1200,theme='carros'),
        'cars_detour':dict(rows=[(100,chat('football','vamos falar de futebol'))],seconds=1200,theme='carros')}
    report={}
    for name,args in scenarios.items():
        result=simulate(**args);report[name]=result['metrics']
        if name in {'gifts','greetings','humor','unknown_67','emoji','chat_gift'}:
            report[name]['sample_speech']=[s.text for s in result['speech']]
        if name.startswith('cars'):
            report[name]['cars_mentions']=sum('carros' in s.text for s in result['speech'])
            report[name]['final_topic']=result['monitor'].presenter.engagement.producer.state.current_topic
        report[name]['real_gemini_calls']=result['monitor'].generator.gemini.calls_made
    return report

if __name__=='__main__':
    import sys
    from pathlib import Path
    result=simulation_report() if '--report' in sys.argv else simulate()['metrics']
    if '--report' in sys.argv:
        Path(__file__).with_name('live_flow_4_simulation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))
