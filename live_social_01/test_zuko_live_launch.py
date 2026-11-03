import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
import wave
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'npc_runtime'))

from zuko_live_launch import LiveLaunchController
from zuko_local_tts import VoiceHealth,LocalVoiceUnavailable


class Root:
    def __init__(self):self.callbacks=[]
    def after(self,delay,callback):self.callbacks.append(callback)


class Monitor:
    def __init__(self):
        self.reading=False;self.local_test_mode=False;self.source='tiktok-sim';self.session_epoch=0
        self.voice_health=VoiceHealth();self._voice_check={'state':'UNVERIFIED'}
        self.voice=SimpleNamespace(current=None,queue=[],cancel_current=Mock(),cancel_preview=Mock(),stop=Mock())
        self.director=SimpleNamespace(invalidate=Mock())
        self.zuko=SimpleNamespace(set_auto=Mock(return_value=True),autonomy=SimpleNamespace(memory=object()),
            litellm=SimpleNamespace(readiness_snapshot=lambda:{'state':'PRONTO'}),
            gemini_budget=SimpleNamespace(snapshot=lambda epoch:{'authorized':False}))
        self.npc=SimpleNamespace(state='OFF',records=[],presentation_status={},error='',open=self.open,
            manual_animation=self.motion,close_npc=Mock())
        self.soundtrack=SimpleNamespace(start=Mock(),stop=Mock())
        self.tiktok_source=SimpleNamespace(simulation=True,is_connected=lambda:False,
            health=lambda:{'connection':'SIMULATOR','broadcaster':'@seu_canal'})
        self.set_platform=Mock(return_value=True)
        self._log=Mock()
    def open(self):self.npc.state='ACTIVE';self.npc.presentation_status={'animation':'Idle','speaking':False}
    def motion(self,name,repeat):
        self.npc.records.append({'name':'MANUAL_SENT','animation':name})
        self.npc.presentation_status['animation']=name
        return True
    def begin_voice_check(self):
        self._voice_check={'state':'RUNNING','started':True}
        self.npc.presentation_status['speaking']=True
        return True
    def voice_check_snapshot(self):return dict(self._voice_check)
    def voice_ready_for_text(self):return self.voice_health.snapshot()['ready'] and not self._launch_preparing


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.root=Root();self.monitor=Monitor();self.clock=0
        self.start=Mock(side_effect=lambda:setattr(self.monitor,'reading',True))
        self.stop=Mock(side_effect=lambda:setattr(self.monitor,'reading',False))
        self.updates=[]
        self.controller=LiveLaunchController(self.root,lambda:self.monitor,lambda *v:self.updates.append(v),
            self.start,self.stop,clock=lambda:self.clock,environment=lambda m:{'workspace':'test'},
            studio=lambda:{'open':False},music=lambda m:{'tracks':['one','two']},simulation=True)
        self.addCleanup(self.controller.close)
    def tick(self):
        if self.controller._future:self.controller._future.result(timeout=2)
        self.root.callbacks.pop(0)()
    def voice_phase(self):
        self.assertTrue(self.controller.start())
        for i in range(8):
            self.tick()
            if self.controller.state=='PREPARING_VOICE':return
        self.fail('voice phase not reached')
    def ready(self):
        self.voice_phase();self.tick()
        self.monitor.voice_health.update('PLAYING',voice='Microsoft Maria',backend='winrt')
        self.monitor.voice_health.update('READY')
        self.monitor._voice_check['state']='READY'
        self.monitor.npc.presentation_status['speaking']=False
        while self.controller.busy:self.tick()
        self.assertEqual(self.controller.state,'READY')
    def test_waits_for_voice_playback_and_bidirectional_godot(self):
        self.voice_phase()
        self.assertEqual(self.start.call_count,0)
        self.tick();self.assertEqual(self.controller.state,'PREPARING_VOICE')
        self.monitor._voice_check={'state':'FAILED','error':'no audio'};self.tick()
        self.assertEqual(self.controller.state,'FAILED');self.start.assert_not_called()
    def test_ready_does_not_start_music_auto_or_claim_public_broadcast(self):
        self.ready();self.monitor.soundtrack.start.assert_not_called()
        self.assertNotIn(unittest.mock.call(True),self.monitor.zuko.set_auto.call_args_list)
        self.assertEqual(self.controller.facts['public_broadcast'],'NOT_CONFIRMED')
        self.assertEqual(self.controller.steps[5]['state'],'SIMULATED')
        self.assertFalse(self.controller.facts['tiktok']['confirmed_real'])
        self.assertTrue(all(s['state']=='PASS' for i,s in enumerate(self.controller.steps) if i!=5))
    def test_selected_simulator_is_not_replaced_by_real_tiktok_reader(self):
        self.controller.simulation=False
        self.monitor.source='tiktok-sim'
        self.monitor.tiktok_source.simulation=True
        self.ready()
        self.monitor.set_platform.assert_not_called()
        self.assertEqual(self.controller.steps[5]['state'],'SIMULATED')
        self.assertTrue(self.controller.facts['tiktok']['simulation'])
        self.assertTrue(self.monitor.reading)
    def test_explicit_activation_stop_and_restart(self):
        self.ready();self.assertTrue(self.controller.activate(start_music=True))
        self.monitor.soundtrack.start.assert_called_once()
        self.assertTrue(self.controller.stop());self.monitor.voice.stop.assert_called_once()
        self.monitor.soundtrack.stop.assert_called_once()
        self.assertEqual(self.monitor.npc.presentation_status['animation'],'Idle')
        self.assertTrue(self.controller.start())
    def test_duplicate_start_is_rejected(self):
        self.controller.start();self.assertFalse(self.controller.start())
    def test_cancel_releases_preparing_gate_and_cancels_preview(self):
        self.voice_phase();self.controller.cancel()
        self.assertFalse(self.monitor._launch_preparing)
        self.monitor.voice.cancel_preview.assert_called_once()
        self.assertEqual(self.controller.state,'CANCELLED')
    def test_godot_without_inbound_confirmation_times_out(self):
        self.controller.start();self.tick()
        self.monitor.npc.presentation_status={};self.clock=50;self.tick()
        self.assertEqual(self.controller.state,'FAILED');self.start.assert_not_called()
    def test_completed_audio_without_godot_speaking_is_not_ready(self):
        self.voice_phase();self.monitor.npc.presentation_status['speaking']=False
        self.monitor._voice_check={'state':'READY','started':True};self.tick()
        self.assertEqual(self.controller.state,'PREPARING_VOICE')
    def test_network_failure_is_exposed_separately_from_local_readiness(self):
        self.controller.simulation=False;self.monitor.tiktok_source.simulation=False
        self.monitor.tiktok_source.health=lambda:{'connection':'ERROR','reason':'CONNECTION_FAILED'}
        self.ready();self.assertEqual(self.controller.facts['tiktok']['reason'],'CONNECTION_FAILED')
        self.assertEqual(self.controller.steps[5]['state'],'FAIL')
        self.assertFalse(self.controller.facts['tiktok']['confirmed_real'])
        self.assertEqual(self.controller.facts['public_broadcast'],'NOT_CONFIRMED')
    def test_reader_connection_passes_only_after_real_connect_confirmation(self):
        self.controller.simulation=False
        self.monitor.tiktok_source.simulation=False
        self.monitor.tiktok_source.is_connected=lambda:True
        self.monitor.tiktok_source.health=lambda:{'connection':'CONNECTED','reason':'','broadcaster':'@seu_canal'}
        self.ready()
        self.assertEqual(self.controller.steps[5]['state'],'PASS')
        self.assertTrue(self.controller.facts['tiktok']['confirmed_real'])
    def test_reader_timeout_remains_pending(self):
        self.controller.simulation=False;self.monitor.tiktok_source.simulation=False
        self.monitor.tiktok_source.health=lambda:{'connection':'CONNECTING','reason':'timeout'}
        self.voice_phase();self.tick()
        self.monitor.voice_health.update('PLAYING',voice='Microsoft Maria',backend='winrt')
        self.monitor.voice_health.update('READY');self.monitor._voice_check['state']='READY'
        self.monitor.npc.presentation_status['speaking']=False
        while self.controller.state!='CONNECTING_TIKTOK':self.tick()
        self.clock=self.controller._deadline-5
        self.tick()
        while self.controller.busy:self.tick()
        self.assertEqual(self.controller.steps[5]['state'],'PENDING')
    def test_environment_error_prevents_components_starting(self):
        self.controller.environment=lambda m:(_ for _ in ()).throw(RuntimeError('wrong workspace'))
        self.controller.start()
        while not self.controller._future.done():time.sleep(.001)
        self.root.callbacks.pop(0)()
        self.assertEqual(self.controller.state,'FAILED');self.start.assert_not_called()
    def test_voice_failure_after_activation_stops_auto_and_music(self):
        self.ready();self.controller.activate(start_music=True)
        self.monitor.voice_health.update('UNAVAILABLE',error='device lost')
        self.controller.check_runtime()
        self.assertEqual(self.controller.state,'FAILED')
        self.monitor.soundtrack.stop.assert_called_once();self.stop.assert_called_once()
    def test_godot_disconnect_revokes_readiness(self):
        self.ready();self.monitor.npc.state='ERROR';self.controller.check_runtime()
        self.assertEqual(self.controller.state,'FAILED')
    def test_existing_stop_control_updates_central_state(self):
        self.ready();self.controller.activate(start_music=True)
        self.monitor.reading=False
        self.controller.check_runtime()
        self.assertEqual(self.controller.state,'IDLE')
        self.monitor.soundtrack.stop.assert_called_once()


class VoiceSafetyTests(unittest.TestCase):
    def test_health_requires_actual_completed_playback(self):
        h=VoiceHealth();h.update('PLAYING');self.assertFalse(h.snapshot()['ready'])
        h.update('READY');self.assertTrue(h.snapshot()['ready'])
        h.update('UNAVAILABLE',error='failed');self.assertFalse(h.snapshot()['ready'])
    def test_generation_and_auto_are_blocked_before_provider_calls(self):
        from zuko_presenter import ZukoPresenter
        presenter=ZukoPresenter.__new__(ZukoPresenter)
        presenter.monitor=SimpleNamespace(voice_ready_for_text=lambda:False)
        presenter.log=Mock()
        unit=SimpleNamespace(metadata={},unit_id='blocked')
        self.assertEqual(presenter._response_bounded(None,unit,0),(None,'VOICE_UNAVAILABLE'))
        self.assertFalse(presenter.set_auto(True))
    def test_local_fallback_tries_other_available_ptbr_voice(self):
        import zuko_local_tts as local
        rows=[{'name':'Microsoft Maria','backend':'winrt','language':'pt-BR'},
              {'name':'Microsoft Daniel','backend':'winrt','language':'pt-BR'}]
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'out.wav';seen=[]
            def run(text,path,name,rate,cancelled,**kwargs):
                seen.append(name)
                if 'Maria' in name:raise LocalVoiceUnavailable('unavailable')
                with wave.open(str(output),'wb') as audio:
                    audio.setparams((1,2,16000,0,'NONE','not compressed'));audio.writeframes(b'\xe8\x03'*1600)
                return '{}'
            with patch.object(local,'installed_voices',return_value=rows),patch.object(local.worker,'synthesize',side_effect=run):
                actual=local.synthesize('Frase real.',output)
            self.assertEqual(actual['name'],'Microsoft Daniel')
            self.assertEqual(seen,['Microsoft Maria','Microsoft Daniel'])
    def test_missing_ptbr_voice_does_not_substitute_other_language(self):
        import zuko_local_tts as local
        with patch.object(local,'_candidates',[]),patch.object(local.worker,'list_voices',return_value=[]),patch.object(local,'run_helper',return_value='[]'):
            with self.assertRaises(LocalVoiceUnavailable):local.installed_voices(refresh=True)
    def test_empty_text_never_starts_synthesis(self):
        import zuko_local_tts as local
        with patch.object(local.worker,'synthesize') as synth:
            with self.assertRaises(LocalVoiceUnavailable):local.synthesize('  ','unused.wav')
            synth.assert_not_called()
    def test_silent_wav_is_rejected_before_playback(self):
        import zuko_local_tts as local
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'silent.wav'
            def silent(*args,**kwargs):
                with wave.open(str(output),'wb') as audio:
                    audio.setparams((1,2,16000,0,'NONE','not compressed'));audio.writeframes(bytes(3200))
            with patch.object(local.worker,'synthesize',side_effect=silent),patch.object(local,'installed_voices',return_value=[]):
                with self.assertRaisesRegex(LocalVoiceUnavailable,'LOCAL_WAV_SILENT'):local.synthesize('Teste.',output)


class ReconnectTests(unittest.TestCase):
    def run_source(self,category):
        from live_tiktok_real_source import TikTokRealEventSource
        source=TikTokRealEventSource('seu_canal');attempts=[]
        def session(generation):
            attempts.append(generation)
            source._state_set('ERROR',category)
        source._session_runner=session
        source._stopping.wait=lambda seconds:False
        self.assertTrue(source.start())
        source._thread.join(2);self.assertFalse(source._thread.is_alive())
        return source,attempts
    def test_transient_network_retries_are_bounded(self):
        source,attempts=self.run_source('CONNECTION_FAILED')
        self.assertEqual(len(attempts),4);self.assertEqual(source.health()['reconnect_attempts'],3)
    def test_auth_failure_does_not_retry(self):
        source,attempts=self.run_source('AUTH_REQUIRED')
        self.assertEqual(len(attempts),1)
    def test_hard_network_access_denial_does_not_retry(self):
        source,attempts=self.run_source('NETWORK_ACCESS_DENIED')
        self.assertEqual(len(attempts),1)
    def test_stop_and_new_start_reset_retry_budget(self):
        source,attempts=self.run_source('CONNECTION_FAILED');source.stop()
        self.assertTrue(source.start());source._thread.join(2)
        self.assertEqual(len(attempts),8)


class GodotFailureTests(unittest.TestCase):
    def test_permission_error_is_explained_and_not_retried(self):
        import npc_panel_bridge as module
        bridge=module.NPCPanelBridge.__new__(module.NPCPanelBridge)
        bridge._cleanup=lambda:None;bridge.port=18765;bridge.stopping=False
        def blocked():
            denied=PermissionError('sandbox socket access');denied.winerror=10013
            raise ConnectionError('local transport') from denied
        client=SimpleNamespace(connect=Mock(side_effect=blocked))
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'RUNTIME',Path(folder)),\
                patch.object(module,'Runtime'),patch.object(module,'ShowClient',return_value=client):
            try:
                with self.assertRaisesRegex(RuntimeError,'TCP_LOCAL_ACCESS_DENIED'):bridge._open()
                self.assertEqual(client.connect.call_count,1)
            finally:
                if bridge.lease:bridge.lease.close()


if __name__=='__main__':unittest.main()
