import unittest,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from test_zuko_ai_only import ZukoAIOnlyTests,FakeAI
from zuko_presenter import ZukoPresenter
from live_monitor import LiveMonitor
class SelectionTests(unittest.TestCase):
 def make(self):
  p=ZukoAIOnlyTests().make_presenter();m=p.monitor;m.zuko=p
  p.litellm.gemini_model='gemini-2.5-flash-lite'
  m.writer=SimpleNamespace(set_mode=lambda mode:setattr(m.writer,'mode',mode),drain_logs=lambda:[],mode='MISTO')
  m._log=lambda *a:None
  return p,m
 def test_dashboard_callback_selects_authorized_local_gemini(self):
  p,m=self.make();p.gemini_budget.authorize(3,0)
  LiveMonitor.set_writer_mode(m,'GEMINI+')
  event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Local',author_key='local',text='Como funciona?',gift_type='')
  text,provider=p._response_bounded(event,ZukoAIOnlyTests.unit('selection'),0)
  self.assertEqual(p.provider_mode,'GEMINI+');self.assertEqual(provider,'GEMINI');self.assertEqual(p.litellm.calls,1)
 def test_local_session_initialization_allows_existing_authorization(self):
  p,m=self.make();p.gemini_budget.epoch=None;m.reading=False;m.local_test_mode=False
  m.telemetry=SimpleNamespace(set_local_mode=lambda value:None);m.set_state=lambda state:None
  m.director.invalidate=lambda:None;m.director.set_paused=lambda value:None
  LiveMonitor.set_local_mode(m,True)
  self.assertEqual(p.gemini_budget.authorize(2,m.session_epoch),(True,'authorized'))
  used=p.gemini_budget.snapshot(0);LiveMonitor.set_local_mode(m,True)
  self.assertEqual(used,p.gemini_budget.snapshot(0))
 def test_selection_does_not_grant_authorization(self):
  p,m=self.make();LiveMonitor.set_writer_mode(m,'GEMINI+')
  self.assertFalse(p.gemini_budget.snapshot(0)['authorized'])
  self.assertIn('aguardando AUTORIZAR TEXTO',p.provider_status_text())
 def test_fallback_and_active_model_display_are_truthful(self):
  p,m=self.make()
  with tempfile.TemporaryDirectory() as folder:
   p.trace_path=Path(folder)/'trace.jsonl';p.log=ZukoPresenter.log.__get__(p)
   p.log('AI_PROVIDER_FALLBACK',provider='OLLAMA_LOCAL',reason='GEMINI_TIMEOUT')
   p.log('AI_PROVIDER_RESULT',provider='OLLAMA_LOCAL',model='qwen3:1.7b')
   status=p.provider_status_text();self.assertIn('qwen3:1.7b',status);self.assertIn('GEMINI_TIMEOUT',status)
   p.log('AI_PROVIDER_RESULT',provider='GEMINI_LITELLM',model='gemini-2.5-flash-lite')
   self.assertIn('gemini-2.5-flash-lite',p.provider_status_text());self.assertEqual(p.provider_reason,'')
 def test_dashboard_tick_keeps_actual_provider_status(self):
  from live_dashboard_v2 import LiveDashboardV2
  from live_dashboard import LiveDashboard
  from unittest.mock import patch
  p,m=self.make();d=LiveDashboardV2.__new__(LiveDashboardV2);d.runtime_monitor=m;d.writer_status=Mock();m.dashboard=d
  m.writer.snapshot=lambda:{'WRITER MODE':m.writer.mode,'GEMINI_WRITER_SPEECH':0,'LOCAL_WRITER_SPEECH':0,'LOCAL_FALLBACK_SPEECH':0}
  p.litellm.readiness_snapshot=lambda:{'state':'PRONTO'}
  p.provider_mode='GEMINI+';p.active_provider='GEMINI_LITELLM';p.active_model='gemini-2.5-flash-lite'
  with patch.object(LiveDashboard,'_tick',lambda self:self.writer_status.configure(text='legacy status')):d._tick()
  self.assertIn('gemini-2.5-flash-lite',d.writer_status.configure.call_args.kwargs['text'])
 def test_presenter_counters_are_separate_from_writer(self):
  p,m=self.make()
  with tempfile.TemporaryDirectory() as folder:
   p.trace_path=Path(folder)/'trace.jsonl';p.log=ZukoPresenter.log.__get__(p)
   p.stats['ZUKO_GEMINI_REAL_CALLS']=1
   p.log('AI_PROVIDER_RESULT',provider='GEMINI_LITELLM',model='gemini-2.5-flash-lite')
   snapshot=p.snapshot()
   self.assertEqual(snapshot['ZUKO_GEMINI_REAL_CALLS'],1)
   self.assertEqual(snapshot['ZUKO_GEMINI_SUCCESSES'],1)
   self.assertEqual(snapshot['ZUKO_GEMINI_ERRORS'],0)
   self.assertFalse(p.gemini_budget.snapshot(0)['authorized'])
if __name__=='__main__':unittest.main()
