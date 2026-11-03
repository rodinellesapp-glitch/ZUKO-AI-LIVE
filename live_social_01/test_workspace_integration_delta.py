import unittest,time,threading
from types import SimpleNamespace
from unittest.mock import Mock,patch
from live_director import LiveDirectorManager,DirectorUnit
from live_monitor import LiveMonitor
from live_tiktok_real_source import TikTokRealEventSource
from live_tiktok_adapter import TikTokLiveAdapter
from zuko_presenter import ZukoPresenter

class WorkspaceIntegrationTests(unittest.TestCase):
 def make(self):
  d=LiveDirectorManager(lambda u:None)
  self.addCleanup(d.close)
  return d
 def add(self,d,i):
  u=DirectorUnit(str(i),'AUDIENCE','id'+str(i),classification='QUESTION')
  self.assertTrue(d.submit(u));d.register_audience(u,'João '+str(i));return u
 def test_current_plus_four_waiting_and_overflow(self):
  d=self.make()
  for i in range(7):self.add(d,i)
  d.audience_state('0','respondendo');x=d.audience_snapshot()
  self.assertEqual(x['current']['id'],'0');self.assertEqual(len(x['rows']),4);self.assertEqual(x['extra'],2)
 def test_new_autonomy_cannot_compete_with_queued_question(self):
  d=self.make();self.add(d,1);auto=DirectorUnit('auto','PRESENTER','')
  self.assertFalse(d.submit(auto));self.assertEqual(auto.metadata['zuko_outcome_reason'],'AUDIENCE_PRIORITY_WAIT')
  self.assertEqual(len(d.pending_units),1)
 def test_autonomy_waits_for_queued_audio_and_manual_control_is_retained(self):
  d=self.make();u=self.add(d,1)
  d.pending_units.remove(u);u.status='COMPLETED';d.audience_state('1','aguardando áudio')
  self.assertFalse(d.submit(DirectorUnit('auto','PRESENTER','')))
  self.assertTrue(d.submit(DirectorUnit('manual','HUMAN_COMMAND','operator')))
 def test_synthesis_racing_dispatch_does_not_regress_to_generated(self):
  d=self.make();self.add(d,1)
  def dispatch(u):
   u.metadata['zuko_dispatch_outcome']='RESPONSE_QUEUED';d.audience_state(u.unit_id,'sintetizada')
  d.dispatch=dispatch;d.run_once();self.assertEqual(d.audience_snapshot()['rows'][0]['state'],'sintetizada')
 def test_real_synthesis_callback_updates_same_director_unit(self):
  d=self.make();self.add(d,1)
  m=SimpleNamespace(director=d,telemetry=SimpleNamespace(sample=lambda *a:None),root=SimpleNamespace(after=lambda *a:None))
  LiveMonitor._audio_synthesized(m,SimpleNamespace(comment_id='1',source='ZUKO',text='Fala.',provider='ZUKO_GEMINI'),10)
  self.assertEqual(d.audience_snapshot()['rows'][0]['state'],'sintetizada')
 def normalized(self,nickname,handle,ident='1'):
  source=TikTokRealEventSource(unique_id='offline_host',sdk_loader=lambda:None)
  source._state='CONNECTED';source._generation=1;source._caps['chat']=True
  user=SimpleNamespace(nickname=nickname,unique_id=handle,id=123456)
  raw=SimpleNamespace(user=user,common=SimpleNamespace(msg_id=ident,create_time=None),content='Como funciona?')
  source._receive('COMMENT',raw,1)
  event=TikTokLiveAdapter(source).normalize(source.read_event())
  self.assertIsNotNone(event)
  return event
 def test_public_nickname_and_handle_fallback_survive_normalization(self):
  for nickname,handle,expected in [('João 😊','public_handle','João 😊'),(None,'public_handle','public_handle')]:
   e=self.normalized(nickname,handle)
   self.assertEqual(e.author_name,expected)
   p=ZukoPresenter.__new__(ZukoPresenter);p.inputs={'event':e}
   self.assertEqual(p._audience_name_for(DirectorUnit('event','AUDIENCE','internal')),expected)
 def test_internal_identifier_never_becomes_public_name(self):
  e=self.normalized(None,None);self.assertIsNone(e.author_name)
  p=ZukoPresenter.__new__(ZukoPresenter);p.inputs={'event':e}
  self.assertEqual(p._audience_name_for(DirectorUnit('event','AUDIENCE','internal')),'')
 def test_same_public_name_keeps_independent_correlations(self):
  d=self.make();a=self.add(d,1);b=self.add(d,2)
  a.metadata['public_name']=b.metadata['public_name']='Ana'
  d.audience_state('1','concluído')
  self.assertEqual(d.audience_snapshot()['rows'][0]['id'],'2')

 def test_normalized_name_reaches_fake_gemini_tts_and_same_overlay(self):
  from test_zuko_ai_only import ZukoAIOnlyTests,FakeLiteLLM
  from zuko_presenter import ZukoAI
  p=ZukoAIOnlyTests().make_presenter(real=True);p.ai.format_text=ZukoAI.format_text
  p.litellm=FakeLiteLLM(text='Resposta completa à sua pergunta.')
  p.litellm.gemini_model='gemini-3.8-flash';p.gemini_budget.authorize(5,0)
  event=self.normalized('Érica 😊','public_erica');p.inputs={'named':event}
  d=LiveDirectorManager(p.dispatch);self.addCleanup(d.close);p.monitor.director=d
  d.audience_name_resolver=p._audience_name_for
  unit=DirectorUnit('named','AUDIENCE',event.author_id,classification='QUESTION')
  self.assertTrue(d.submit(unit));self.assertEqual(d.audience_snapshot()['rows'][0]['name'],'Érica 😊')
  names=[];call=p.litellm.gemini_response
  def generate(*args,**kwargs):names.append(args[1]);return call(*args,**kwargs)
  p.litellm.gemini_response=generate
  self.assertTrue(d.run_once());self.assertEqual(names,['Érica 😊'])
  response=p.monitor.queued[0];self.assertEqual(response.author,'Érica 😊');self.assertIn('Érica 😊',response.text)
  p.tts_result('TTS_INICIO',response);self.assertEqual(d.audience_snapshot()['current']['name'],'Érica 😊')
  p.tts_result('TTS_OK',response);self.assertEqual(d.audience_snapshot()['current'],{})
