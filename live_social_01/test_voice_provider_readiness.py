"""Offline provider readiness, retained audience work and real-event state boundaries."""
import os,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from live_monitor import LiveMonitor
from live_director import LiveDirectorManager,DirectorUnit
from zuko_local_tts import VoiceHealth
from zuko_presenter import ZukoPresenter
import test_zuko_ai_only as fixtures

class ProviderReadinessTests(unittest.TestCase):
    def setUp(self):
        self.m=LiveMonitor.__new__(LiveMonitor);self.m.voice_health=VoiceHealth()
        self.grant={'session_active':True,'authorized':True,'remaining':2}
        self.config=patch('zuko_voice_config.load',return_value={'engine':'Gemini TTS','voice':'Puck'}).start()
        patch('zuko_voice_config.authorization_status',side_effect=lambda:dict(self.grant)).start()
        patch.dict(os.environ,{'GEMINI_API_KEY':'offline-placeholder'}).start()
        self.addCleanup(patch.stopall)
    def ready(self):return self.m.voice_ready_for_text()
    def test_authorized_cloud_does_not_require_local_preview(self):
        self.assertTrue(self.ready());self.assertFalse(self.m.voice_health.snapshot()['ready'])
    def test_authorization_required_despite_local_ready(self):
        self.m.voice_health.update('READY');self.grant['authorized']=False;self.assertFalse(self.ready())
    def test_active_session_required(self):
        self.grant['session_active']=False;self.assertFalse(self.ready())
    def test_key_required(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':''}):self.assertFalse(self.ready())
    def test_preparation_still_blocks(self):
        self.m._launch_preparing=True;self.assertFalse(self.ready())
    def test_local_engine_still_requires_confirmed_playback(self):
        self.config.return_value={'engine':'Microsoft Maria'}
        self.assertFalse(self.ready());self.m.voice_health.update('READY');self.assertTrue(self.ready())
    def test_old_local_error_does_not_poison_cloud(self):
        self.m.voice_health.update('UNAVAILABLE',error='old local failure');self.assertTrue(self.ready())
    def test_temporary_authorization_loss_retains_three_comments_then_recovers(self):
        dispatched=[];d=LiveDirectorManager(lambda u:dispatched.append(u.unit_id));d.voice_ready=self.ready
        for i in range(3):
            u=DirectorUnit(str(i),'AUDIENCE','public',ttl=60);self.assertTrue(d.submit(u));d.register_audience(u,'Pessoa '+str(i))
        self.grant['authorized']=False
        self.assertFalse(d.run_once());self.assertEqual(d.state,'WAITING_VOICE');self.assertEqual(len(d.pending_units),3)
        self.assertEqual(len(d.audience_snapshot()['rows']),3)
        self.grant['authorized']=True
        for _ in range(3):self.assertTrue(d.run_once())
        self.assertEqual(len(dispatched),3)
    def test_cooldown_still_holds_without_consuming_comment(self):
        d=LiveDirectorManager(Mock());d.voice_ready=self.ready;d.generation_ready_at=lambda:time.monotonic()+10
        d.submit(DirectorUnit('cool','AUDIENCE','a',ttl=60));self.assertFalse(d.run_once())
        self.assertEqual(d.state,'WAITING_GEMINI_SLOT');self.assertEqual(len(d.pending_units),1);d.dispatch.assert_not_called()
    def test_eligible_real_source_question_reaches_mock_gemini_without_bypass(self):
        p=fixtures.ZukoAIOnlyTests().make_presenter();p.monitor.voice_ready_for_text=self.ready
        p._is_real_tiktok_session=lambda:True;p.monitor.local_test_mode=False
        self.assertTrue(p.gemini_budget.authorize(1,0)[0])
        event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Pessoa',author_key='public',text='Como funciona Python?',gift_type='')
        unit=fixtures.ZukoAIOnlyTests.unit('eligible-real-source')
        self.assertNotIn('text_only_authorized',unit.metadata)
        text,provider=p._response_bounded(event,unit,0)
        self.assertTrue(text);self.assertEqual(provider,'GEMINI');self.assertEqual(p.litellm.calls,1)
    def prepare_delivery(self):
        m=self.m;m.root=Mock();m.voice=Mock();m.telemetry=Mock();m._log=Mock();m.director_snapshot=lambda:{}
        d=LiveDirectorManager(Mock());m.director=d
        p=ZukoPresenter.__new__(ZukoPresenter);p.monitor=m;p.deliveries={};p.lock=threading.RLock();p.autonomy=None;m.zuko=p
        response=SimpleNamespace(comment_id='reply',author='Pessoa',source='ZUKO',provider='ZUKO_GEMINI')
        u=DirectorUnit('reply','AUDIENCE','public',ttl=60);d.submit(u);d.register_audience(u,'Pessoa')
        return m,d,response
    def test_cloud_error_does_not_clear_other_pending_speech_or_poison_local_health(self):
        m,d,r=self.prepare_delivery();LiveMonitor._tts_event(m,'TTS_ERRO',r,'transient timeout')
        m.voice.cancel_current.assert_not_called();self.assertEqual(m.voice_health.snapshot()['state'],'UNVERIFIED')
        self.assertTrue(self.ready());self.assertFalse(d.audience_snapshot()['current']);self.assertFalse(d.audience_snapshot()['rows'])
    def test_synthesis_is_not_spoken_and_actual_start_end_update_overlay(self):
        m,d,r=self.prepare_delivery();d.audience_state('reply','sintetizada')
        self.assertFalse(d.audience_snapshot()['current'])
        LiveMonitor._tts_event(m,'TTS_INICIO',r);self.assertTrue(d.audience_snapshot()['current'])
        LiveMonitor._tts_event(m,'TTS_OK',r);snap=d.audience_snapshot();self.assertFalse(snap['current']);self.assertFalse(snap['rows'])
        m.voice.cancel_current.assert_not_called()

if __name__=='__main__':unittest.main()
