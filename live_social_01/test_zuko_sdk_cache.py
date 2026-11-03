import unittest,sys
from unittest.mock import Mock,patch
from types import SimpleNamespace
from zuko_litellm import LiteLLMTransport
class CacheTests(unittest.TestCase):
 def test_same_vertex_cache_is_prepared_before_ready(self):
  client=Mock();t=LiteLLMTransport({});t._get_async_completion=lambda:None;t._get_completion=lambda:None
  with patch.dict(sys.modules,{'litellm.main':SimpleNamespace(vertex_chat_completion=client)}):
   t.warmup();t._warmup_thread.join(2)
  client.get_access_token.assert_called_once_with(credentials=None,project_id=t.vertex_project)
  self.assertEqual(t.readiness_snapshot()['state'],'PRONTO')
  self.assertIn('sdk_adc',t.readiness_snapshot()['stages_ms'])
 def test_auth_failure_blocks_ready(self):
  client=Mock();client.get_access_token.side_effect=RuntimeError('simulated')
  t=LiteLLMTransport({});t._get_async_completion=lambda:None;t._get_completion=lambda:None
  with patch.dict(sys.modules,{'litellm.main':SimpleNamespace(vertex_chat_completion=client)}):
   t.warmup();t._warmup_thread.join(2)
  self.assertEqual(t.readiness_snapshot()['state'],'INDISPONÍVEL')
if __name__=='__main__':unittest.main()
