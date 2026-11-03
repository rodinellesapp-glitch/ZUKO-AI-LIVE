import unittest,time

from unittest.mock import patch

from live_director import LiveDirectorManager,DirectorUnit

from zuko_litellm import LiteLLMTransport

class ReadyTests(unittest.TestCase):

 def test_queue_survives_preparation_then_consumes_normal_ttl(self):

  clock=[0.0];state={'state':'INICIALIZANDO','finished':None};sent=[]

  d=LiveDirectorManager(lambda u:sent.append(u.unit_id),clock=lambda:clock[0]);d.preparation_snapshot=lambda:state

  u=DirectorUnit('a','LOCAL','ana',created_at=0,ttl=10);d.submit(u)

  clock[0]=20;self.assertFalse(d.run_once());self.assertEqual(len(d.pending_units),1)

  state.update(state='PRONTO',finished=20);self.assertTrue(d.run_once());self.assertEqual(sent,['a']);self.assertEqual(u.created_at,20)

 def test_capacity_and_obsolete_messages_preserved(self):

  d=LiveDirectorManager(lambda u:None);d.preparation_snapshot=lambda:{'state':'INICIALIZANDO'}

  for i in range(30):d.submit(DirectorUnit(str(i),'LOCAL','a'))

  self.assertLessEqual(len(d.pending_units),24)

  d.invalidate();self.assertFalse(d.run_once())

 def test_preparation_failure_is_visible(self):

  t=LiteLLMTransport({});t._get_async_completion=lambda:(_ for _ in ()).throw(RuntimeError('fake auth failure'))

  t.warmup();t._warmup_thread.join(1)

  self.assertEqual(t.readiness_snapshot()['state'],'INDISPONÍVEL')

 def test_ready_mock_initialization(self):

  t=LiteLLMTransport({},completion=lambda **kw:None);t.warmup();t._warmup_thread.join(1)

  self.assertEqual(t.readiness_snapshot()['state'],'PRONTO')

 def test_preparation_has_hard_deadline(self):

  t=LiteLLMTransport({});t._ready_started=time.monotonic()-46

  self.assertEqual(t.readiness_snapshot()['state'],'INDISPONÍVEL')

 def test_auth_failure_does_not_become_ready(self):
  import sys
  from types import SimpleNamespace
  from unittest.mock import Mock
  client=Mock();client.get_access_token.side_effect=RuntimeError('fake ADC failure')
  t=LiteLLMTransport({});t._get_async_completion=lambda:None;t._get_completion=lambda:None
  with patch.dict(sys.modules,{'litellm.main':SimpleNamespace(vertex_chat_completion=client)}):
   t.warmup();t._warmup_thread.join(2)
  self.assertEqual(t.readiness_snapshot()['state'],'INDISPONÍVEL')
 def test_generation_timeout_has_one_attempt(self):

  import asyncio

  count=[]

  async def slow(**kw):

   count.append(1);await asyncio.sleep(1)

  t=LiteLLMTransport({},async_completion=slow)

  with self.assertRaises(TimeoutError):asyncio.run(t._run_one({},.01,None))

  self.assertEqual(len(count),1)

 def test_duplicate_does_not_consume_a_second_call(self):

  from test_zuko_ai_only import ZukoAIOnlyTests

  from types import SimpleNamespace

  helper=ZukoAIOnlyTests();p=helper.make_presenter(real=True);p.gemini_budget.authorize(3,0)

  event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='a',author_key='a',text='q',gift_type='')

  for ident,corr in [('id1','c1'),('id1','c2'),('id2','c1')]:p._response_bounded(event,helper.unit(ident,metadata={'correlation_id':corr}),0)

  self.assertEqual(p.litellm.calls,1)

  self.assertEqual(p.gemini_budget.snapshot(0)['used'],1)

if __name__=='__main__':unittest.main()

