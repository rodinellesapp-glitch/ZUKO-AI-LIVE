import queue
import threading
import unittest
import json
import socket
from unittest.mock import patch
from types import SimpleNamespace

from npc_panel_bridge import NPCPanelBridge
from show_tcp import ShowClient
from test_zuko_ai_only import FakeAI, FakeLiteLLM, ZukoAIOnlyTests


class FakeClient:
    def __init__(self, bridge):
        self.bridge = bridge
        self.events = []

    def poll_status(self):
        self.polls=getattr(self,'polls',0)+1
        if self.polls>1:
            self.bridge.stopping=True
        return None

    def send_event(self, *args, **kwargs):
        self.events.append(('event', args, kwargs))
        if args and args[0] == 'talk':
            self.bridge.stopping = True

    def send_auto_animation(self, *args, **kwargs):
        self.events.append(('automatic', args, kwargs))
        self.bridge.stopping = True


def bridge_for_run():
    bridge = NPCPanelBridge.__new__(NPCPanelBridge)
    bridge.stopping = False
    bridge.state = 'ACTIVE'
    bridge.runtime = None
    bridge.client = FakeClient(bridge)
    bridge.speech = 'speech-2'
    bridge.speech_correlation = 'speech-corr'
    bridge.speech_animation = 'Idle'
    bridge.speech_emotion = 'calm'
    bridge.speech_intent = 'comment'
    bridge.godot_speaking = False
    bridge.auto_selector = SimpleNamespace(last_speech_emotion='calm',
        last_speech_intent='comment', speech_gesture=lambda _text: 'Idle',
        emotion_for=lambda _text: 'calm', intent_for=lambda _text: 'comment')
    bridge.auto_movements_enabled = True
    bridge.manual_override = False
    bridge.external_paused = False
    bridge.manual_paused = False
    bridge.pause_provider = lambda: False
    bridge.presentation_status = {}
    bridge.last_scenery_moving = None
    bridge.manual_commands = queue.Queue()
    bridge.commands = queue.Queue()
    bridge.lock = threading.RLock()
    bridge.pending_movements = []
    bridge.auto_commands = [(1, 0.0, 'Wave', 'auto-id', 0.1, 'IDLE')]
    bridge.walk_wave_enabled = False
    bridge.auto_idle_walking = False
    bridge.records = []
    bridge.record = lambda name, **data: bridge.records.append((name, data))
    bridge._movement_record = lambda name, origin, corr=None, **data: bridge.records.append(
        (name, {'origin': origin, 'correlation_id': corr, **data}))
    bridge._cleanup = lambda: None
    return bridge


def bridge_for_status():
    bridge=bridge_for_run()
    bridge.speech=None
    bridge.speech_correlation=None
    bridge.active_speech_correlation=None
    bridge.presentation_status={}
    bridge.last_scenery_moving=None
    bridge.walk_wave_pending=None
    bridge.walk_wave_last_active=False
    bridge.walk_wave_last_error=''
    bridge.walk_combo_pending={}
    bridge.walk_combo_last_errors={}
    bridge.walk_combo_last_active=''
    bridge.walk_combo_enabled={'Wave':False,'Yes':False,'No':False}
    bridge.active_movement=None
    bridge.last_status_key=None
    bridge.walk_context=None
    return bridge


class DashboardMetricTests(unittest.TestCase):
    def test_presenter_metrics_keep_text_providers_and_tts_fallback_separate(self):
        from live_dashboard_v2 import _zuko_metric_lines

        presenter = {
            'ZUKO_GEMINI_REAL_CALLS': 2,
            'ZUKO_GEMINI_SUCCESSES': 2,
            'ZUKO_GEMINI_ERRORS': 0,
            'ZUKO_GEMINI_TEXTS': 2,
            'ZUKO_LOCAL_AI_TEXTS': 1,
            'ZUKO_TEXT_FALLBACKS': 1,
            'ZUKO_GEMINI_TTS_FALLBACKS': 1,
            'ZUKO_GEMINI_DUPLICATES_BLOCKED': 0,
        }
        legacy_writer = {
            'WRITER MODE': 'GEMINI+',
            'GEMINI_WRITER_SPEECH': 0,
            'LOCAL_WRITER_SPEECH': 2,
            'LOCAL_FALLBACK_SPEECH': 2,
        }
        first = _zuko_metric_lines(presenter, legacy_writer)
        second = _zuko_metric_lines(presenter, legacy_writer)
        self.assertEqual(first, second)
        joined = '\n'.join(first)
        self.assertIn('Gemini: 2 chamadas · 2 gerações OK · 0 erros · 2 respostas', joined)
        self.assertIn('Ollama: 1 resposta', joined)
        self.assertIn('Fallback de texto: 1', joined)
        self.assertIn('Fallback de voz/TTS: 1', joined)
        self.assertIn('WRITER LEGADO', joined)
        self.assertIn('Local 2 · fallback 2', joined)
        legacy='\n'.join(__import__('live_dashboard_v2')._legacy_metric_lines(
            legacy_writer,{'GEMINI_CALL_ATTEMPTS_SESSION':0,
                          'GEMINI_CALL_SUCCESS_SESSION':0,'GEMINI_CALL_ERRORS_SESSION':0}))
        self.assertIn('CONTADORES LEGADOS',legacy)
        self.assertIn('GEMINI_CALL_ATTEMPTS_SESSION=0',legacy)

    def test_dashboard_diagnostic_copies_current_and_legacy_counters_labeled(self):
        from live_dashboard import LiveDashboard
        from live_dashboard_v2 import LiveDashboardV2
        class Clipboard:
            def __init__(self):self.value=''
            def clipboard_get(self):return self.value
            def clipboard_clear(self):self.value=''
            def clipboard_append(self,value):self.value+=value
        root=Clipboard()
        dashboard=object.__new__(LiveDashboardV2)
        dashboard.root=root
        dashboard.runtime_monitor=SimpleNamespace(
            zuko=SimpleNamespace(snapshot=lambda:{'ZUKO_GEMINI_REAL_CALLS':2,
                'ZUKO_GEMINI_SUCCESSES':2,'ZUKO_GEMINI_ERRORS':0,'ZUKO_GEMINI_TEXTS':2}),
            writer=SimpleNamespace(snapshot=lambda:{'WRITER MODE':'GEMINI+',
                'GEMINI_WRITER_SPEECH':0,'LOCAL_WRITER_SPEECH':2,'LOCAL_FALLBACK_SPEECH':2}),
            telemetry=SimpleNamespace(snapshot=lambda:{'GEMINI_CALL_ATTEMPTS_SESSION':0,
                'GEMINI_CALL_SUCCESS_SESSION':0,'GEMINI_CALL_ERRORS_SESSION':0}))
        with patch.object(LiveDashboard,'copy_diagnostic',lambda self: self.root.clipboard_append('diagnóstico base')):
            dashboard.copy_diagnostic()
        self.assertIn('TEXTO ZUKO · PRESENTER ATUAL',root.value)
        self.assertIn('Gemini: 2 chamadas · 2 gerações OK',root.value)
        self.assertIn('CONTADORES LEGADOS',root.value)
        self.assertIn('GEMINI_CALL_ATTEMPTS_SESSION=0',root.value)

    def test_dashboard_tick_refreshes_presenter_metrics_without_appending_duplicates(self):
        from live_dashboard import LiveDashboard
        from live_dashboard_v2 import LiveDashboardV2
        class Label:
            def __init__(self,value=''):self.value=value
            def cget(self,_key):return self.value
            def configure(self,**kwargs):self.value=kwargs.get('text',self.value)
        stats={'ZUKO_GEMINI_REAL_CALLS':2,'ZUKO_GEMINI_SUCCESSES':2,
            'ZUKO_GEMINI_ERRORS':0,'ZUKO_GEMINI_TEXTS':2,
            'ZUKO_LOCAL_AI_TEXTS':0,'ZUKO_TEXT_FALLBACKS':0,
            'ZUKO_GEMINI_TTS_FALLBACKS':0,'ZUKO_GEMINI_DUPLICATES_BLOCKED':0}
        zuko=SimpleNamespace(snapshot=lambda:stats,_refresh_provider_status=lambda:None,
            litellm=SimpleNamespace(readiness_snapshot=lambda:{'state':'PRONTO'}),
            gemini_budget=SimpleNamespace(snapshot=lambda _epoch:{'authorized':True}))
        monitor=SimpleNamespace(zuko=zuko,writer=SimpleNamespace(snapshot=lambda:{
            'WRITER MODE':'GEMINI+','GEMINI_WRITER_SPEECH':0,
            'LOCAL_WRITER_SPEECH':2,'LOCAL_FALLBACK_SPEECH':2}),
            telemetry=SimpleNamespace(snapshot=lambda:{'health':{}}),session_epoch=1)
        dashboard=object.__new__(LiveDashboardV2)
        dashboard.runtime_monitor=monitor
        dashboard.metrics=Label()
        dashboard.health=Label()
        dashboard.writer_status=Label()
        def base_tick(self):
            self.metrics.configure(text='CHAMADAS GEMINI 0\nCALL OK/ERRO 0/0\nRESP. IA 0\nFALLBACK 2\nLAT GEMINI 0ms')
        with patch.object(LiveDashboard,'_tick',base_tick):
            dashboard._tick();dashboard._tick()
        self.assertEqual(dashboard.metrics.value.count('TEXTO ZUKO · PRESENTER ATUAL'),1)
        self.assertEqual(dashboard.metrics.value.count('Gemini: 2 chamadas'),1)
        self.assertIn('WRITER LEGADO: GEMINI+',dashboard.writer_status.value)

    def test_two_simulated_gemini_answers_update_presenter_counters_once(self):
        presenter = ZukoAIOnlyTests().make_presenter(ai=FakeAI(), real=True)
        previous_log=presenter.log
        def count_gemini_success(event,**data):
            if event=='AI_PROVIDER_RESULT' and data.get('provider')=='GEMINI_LITELLM':
                presenter.stats['ZUKO_GEMINI_SUCCESSES']+=1
            previous_log(event,**data)
        presenter.log=count_gemini_success
        presenter.gemini_budget.reset(0)
        presenter.gemini_budget.authorize(3, 0)
        for index in range(2):
            text=f'Resposta simulada número {index + 1} sobre a caldeira.'
            presenter.litellm=FakeLiteLLM(text=text)
            event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Ana',
                author_key='ana',text=f'Pergunta {index + 1}',gift_type='',source='TIKTOK',
                received_at=__import__('time').monotonic())
            ident=f'counter-{index}'
            presenter.inputs={ident:event}
            presenter.last_comment=__import__('time').monotonic()-10
            presenter.dispatch(ZukoAIOnlyTests.unit(ident,
                content=SimpleNamespace(author='Ana',text=event.text),
                metadata={'correlation_id':f'corr-{ident}'}))
        snapshot=presenter.snapshot()
        self.assertEqual((snapshot['ZUKO_GEMINI_REAL_CALLS'],
                          snapshot['ZUKO_GEMINI_SUCCESSES'],
                          snapshot['ZUKO_GEMINI_TEXTS'],
                          snapshot['ZUKO_LOCAL_AI_TEXTS']), (2,2,2,0))

    def test_simulated_ollama_fallback_and_tts_fallback_have_separate_counts(self):
        presenter=ZukoAIOnlyTests().make_presenter(ai=FakeAI('Resposta local simulada.'),real=True)
        presenter.gemini_budget.reset(0)
        presenter.gemini_budget.authorize(1,0)
        presenter.litellm=FakeLiteLLM(error='Gemini simulado indisponível')
        event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Ana',author_key='ana',
            text='Como está a caldeira?',gift_type='',source='TIKTOK',
            received_at=__import__('time').monotonic())
        presenter.inputs={'fallback-test':event}
        presenter.last_comment=__import__('time').monotonic()-10
        presenter.dispatch(ZukoAIOnlyTests.unit('fallback-test',
            content=SimpleNamespace(author='Ana',text=event.text),
            metadata={'correlation_id':'corr-fallback-test'}))
        snapshot=presenter.snapshot()
        self.assertEqual(snapshot['ZUKO_LOCAL_AI_TEXTS'],1)
        self.assertEqual(snapshot['ZUKO_TEXT_FALLBACKS'],1)
        lines='\n'.join(__import__('live_dashboard_v2')._zuko_metric_lines(
            {**snapshot,'ZUKO_GEMINI_TTS_FALLBACKS':1},
            {'WRITER MODE':'GEMINI+','GEMINI_WRITER_SPEECH':0,
             'LOCAL_WRITER_SPEECH':2,'LOCAL_FALLBACK_SPEECH':2}))
        self.assertIn('Fallback de texto: 1',lines)
        self.assertIn('Fallback de voz/TTS: 1',lines)

    def test_automatic_movement_waits_while_tts_is_active(self):
        bridge = bridge_for_run()
        bridge._run()
        self.assertEqual(bridge.client.events, [
            ('event', ('talk',), {'speaking': True, 'gesture': 'Idle'})])

    def test_automatic_movement_waits_for_godot_speech_end_after_tts_ok(self):
        bridge=bridge_for_run()
        bridge.speech=None
        bridge.godot_speaking=True
        bridge._run()
        self.assertEqual(bridge.client.events,[])

    def test_tts_idle_speech_is_confirmed_and_returns_idle(self):
        bridge=bridge_for_status()
        response=SimpleNamespace(comment_id='speech-idle',text='Resposta falada.')
        bridge.tts('TTS_INICIO',response)
        bridge._run()
        self.assertEqual(bridge.client.events,[
            ('event',('talk',),{'speaking':True,'gesture':'Idle'})])
        bridge._observe_presentation_status({'animation':'Idle','walking':False,'live':False,
            'paused':False,'manual':False,'reacting':False,'speaking':True})
        self.assertTrue(any(name=='SPEECH_ANIMATION_CONFIRMED' for name,_ in bridge.records))
        bridge.tts('TTS_OK',response)
        bridge._observe_presentation_status({'animation':'Idle','walking':False,'live':False,
            'paused':False,'manual':False,'reacting':False,'speaking':False})
        returned=[row for row in bridge.records if row[0]=='MOVEMENT_RETURN_IDLE']
        self.assertEqual(len(returned),1)
        self.assertEqual(returned[0][1]['origin'],'SPEECH')

    def test_tts_wave_speech_is_confirmed_and_returns_idle(self):
        bridge=bridge_for_status()
        bridge.auto_selector.speech_gesture=lambda _text:'Wave'
        response=SimpleNamespace(comment_id='speech-wave',text='Obrigado pela pergunta!')
        bridge.tts('TTS_INICIO',response)
        bridge._run()
        self.assertEqual(bridge.client.events,[
            ('event',('talk',),{'speaking':True,'gesture':'Wave'})])
        bridge._observe_presentation_status({'animation':'Wave','walking':False,'live':False,
            'paused':False,'manual':False,'reacting':True,'speaking':True})
        self.assertTrue(any(name=='SPEECH_ANIMATION_CONFIRMED' for name,_ in bridge.records))
        bridge.tts('TTS_OK',response)
        bridge._observe_presentation_status({'animation':'Idle','walking':False,'live':False,
            'paused':False,'manual':False,'reacting':False,'speaking':False})
        self.assertTrue(any(name=='MOVEMENT_RETURN_IDLE' for name,_ in bridge.records))

    def test_tcp_status_accepts_godot_speaking_confirmation(self):
        client=ShowClient()
        receiver,sender=socket.socketpair()
        try:
            client._socket=receiver
            sender.sendall((json.dumps({'type':'presentation_status','state':{
                'walking':False,'live':False,'paused':False,'manual':False,
                'animation':'Idle','speaking':True}})+'\n').encode('utf-8'))
            status=client.poll_status()
            self.assertTrue(status['speaking'])
            self.assertEqual(status['animation'],'Idle')
        finally:
            client.close()
            sender.close()


if __name__ == '__main__':
    unittest.main()
