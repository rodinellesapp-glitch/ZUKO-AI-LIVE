import asyncio
import json
import threading
import time
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace

from zuko_litellm import (LiteLLMTransport, ProviderDiagnosticError,
                          generation_error_diagnostics)
from zuko_presenter import ZukoAI, ZukoPresenter


def result(text):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=text))])


class LiteLLMTransportTests(unittest.TestCase):
    def test_gemini_uses_vertex_without_retries_and_keeps_author_context(self):
        calls=[]
        transport=LiteLLMTransport({},completion=lambda **kwargs:(calls.append(kwargs) or result('Resposta nova.')),
            gemini_model='gemini-2.5-flash-lite',vertex_project='project-x',vertex_location='global')
        text=transport.gemini_response('E funciona no celular?','Ana',(),False,False,
            '{"topic":"jogo"}','Responda em pt-BR.',timeout=3,
            correlation_id='corr-ana-2')
        self.assertEqual(text,'Resposta nova.')
        call=calls[0]
        self.assertEqual(call['model'],'vertex_ai/gemini-2.5-flash-lite')
        self.assertEqual((call['vertex_project'],call['vertex_location']),('project-x','global'))
        self.assertEqual((call['num_retries'],call['max_retries']),(0,0))
        self.assertEqual(call['metadata']['correlation_id'],'corr-ana-2')
        self.assertIn('Ana',call['messages'][1]['content'])
        self.assertIn('E funciona no celular?',call['messages'][1]['content'])

    def test_gemini_38_uses_low_thinking_and_a_live_sized_output_budget(self):
        calls=[]
        usage=SimpleNamespace(prompt_tokens=24,completion_tokens=62,total_tokens=86,
            reasoning_tokens=18,completion_tokens_details=SimpleNamespace(reasoning_tokens=18))
        response=SimpleNamespace(model='gemini-3.8-flash',usage=usage,choices=[SimpleNamespace(
            finish_reason='stop',provider_specific_fields={'native_finish_reason':'STOP'},
            message=SimpleNamespace(content='Tudo conectado e pronto para a live!'))])
        transport=LiteLLMTransport({},gemini_model='gemini-3.8-flash',gemini_provider='gemini',
            completion=lambda **kwargs:(calls.append(kwargs) or response))
        text=transport.gemini_response('Dê oi ao chat','Público',(),False,False,'','Responda em pt-BR.')
        self.assertEqual(text,'Tudo conectado e pronto para a live!')
        self.assertEqual(calls[0]['model'],'gemini/gemini-3.8-flash')
        self.assertEqual(calls[0]['max_tokens'],512)
        self.assertEqual(calls[0]['reasoning_effort'],'low')
        self.assertNotIn('temperature',calls[0])
        self.assertEqual(transport.last_response_metadata['finish_reason'],'stop')
        self.assertEqual(transport.last_response_metadata['native_finish_reason'],'STOP')
        self.assertEqual(transport.last_response_metadata['reasoning_tokens'],18)
        self.assertEqual(transport.last_response_metadata['total_tokens'],86)

    def test_gemini_max_tokens_response_is_rejected_with_safe_metadata(self):
        usage=SimpleNamespace(prompt_tokens=124,completion_tokens=512,total_tokens=636,
            reasoning_tokens=252,completion_tokens_details=SimpleNamespace(reasoning_tokens=252))
        response=SimpleNamespace(model='gemini-3.8-flash',usage=usage,choices=[SimpleNamespace(
            finish_reason='length',provider_specific_fields={'native_finish_reason':'MAX_TOKENS'},
            message=SimpleNamespace(content='Fala, galera conectada,'))])
        transport=LiteLLMTransport({},gemini_model='gemini-3.8-flash',gemini_provider='gemini',
            completion=lambda **_kwargs:response)
        with self.assertRaises(ProviderDiagnosticError) as caught:
            transport.gemini_response('Oi','Público',(),False,False,'','Regras curtas.')
        self.assertEqual(caught.exception.diagnostic_code,'GEMINI_OUTPUT_TRUNCATED')
        self.assertEqual(caught.exception.diagnostic_category,'TRUNCATED')
        self.assertEqual(caught.exception.response_metadata['native_finish_reason'],'MAX_TOKENS')
        self.assertEqual(caught.exception.response_metadata['reasoning_tokens'],252)
        self.assertEqual(transport.last_response_metadata['finish_reason'],'length')

    def test_local_max_tokens_response_is_not_returned_as_speech(self):
        response=SimpleNamespace(choices=[SimpleNamespace(finish_reason='length',
            message=SimpleNamespace(content='Resposta cortada'))])
        transport=LiteLLMTransport({'url':'http://127.0.0.1:11434/api/generate',
            'model':'qwen3:1.7b','timeout':12,'num_predict':56},
            completion=lambda **_kwargs:response)
        with self.assertRaises(ProviderDiagnosticError) as caught:
            transport.local_response({'comment':'oi'},'regras')
        self.assertEqual(caught.exception.diagnostic_code,'LOCAL_AI_OUTPUT_TRUNCATED')
        self.assertEqual(caught.exception.response_metadata['finish_reason'],'length')

    def test_ollama_uses_only_configured_loopback_model_and_no_retries(self):
        calls=[]
        transport=LiteLLMTransport({'url':'http://127.0.0.1:11434/api/generate',
            'model':'qwen3:1.7b','timeout':12,'num_predict':56,'think':False,'keep_alive':'120s'},
            completion=lambda **kwargs:(calls.append(kwargs) or result('Resposta local.')))
        self.assertEqual(transport.local_response({'comment':'pergunta'},'regras',
            timeout=2,correlation_id='corr-local-1'),'Resposta local.')
        call=calls[0]
        self.assertEqual(call['model'],'ollama_chat/qwen3:1.7b')
        self.assertEqual(call['max_tokens'],56)
        self.assertIs(call['think'],False)
        self.assertEqual(call['keep_alive'],'120s')
        self.assertEqual(call['api_base'],'http://127.0.0.1:11434')
        self.assertIs(call['think'],False)
        self.assertEqual(call['metadata']['model'],'qwen3:1.7b')
        self.assertEqual((call['num_retries'],call['max_retries']),(0,0))
        self.assertEqual(call['timeout'],2)
        self.assertEqual(call['metadata']['correlation_id'],'corr-local-1')

    def test_local_generation_uses_sync_litellm_route_and_does_not_create_unawaited_coroutine(self):
        calls=[]
        async def async_route(**_kwargs):
            raise AssertionError('Ollama local route must not dispatch through acompletion')
        transport=LiteLLMTransport({'url':'http://127.0.0.1:11434/api/generate',
            'model':'qwen3:1.7b','timeout':12,'num_predict':32},
            completion=lambda **kwargs:(calls.append(kwargs) or result('Resposta local.')),
            async_completion=async_route)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always',RuntimeWarning)
            self.assertEqual(transport.local_response({'comment':'oi'},'regras'), 'Resposta local.')
            self.assertFalse(any('was never awaited' in str(item.message) for item in caught))
        self.assertEqual(len(calls),1)

    def test_sync_provider_rejects_and_closes_awaitable_result(self):
        async def accidental_coroutine(**_kwargs):
            return result('não deve vazar')
        transport=LiteLLMTransport({'url':'http://127.0.0.1:11434/api/generate',
            'model':'qwen3:1.7b','timeout':12,'num_predict':32},completion=accidental_coroutine)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always',RuntimeWarning)
            with self.assertRaisesRegex(ProviderDiagnosticError,'ASYNC_RESULT_FROM_SYNC_PROVIDER'):
                transport.local_response({'comment':'oi'},'regras')
        self.assertFalse(any('was never awaited' in str(item.message) for item in caught))

    def test_empty_answer_and_non_loopback_endpoint_fail_closed(self):
        empty=LiteLLMTransport({},completion=lambda **_kwargs:result('  '))
        with self.assertRaisesRegex(ProviderDiagnosticError,'EMPTY_CONTENT'):
            empty.gemini_response('oi','Ana',(),False,False,'','regras')
        remote=LiteLLMTransport({'url':'http://example.com:11435/api/generate',
            'model':'qwen2.5:1.5b','timeout':12,'num_predict':110},
            completion=lambda **_kwargs:result('não deve chamar'))
        with self.assertRaisesRegex(ValueError,'loopback'):
            remote.local_response({'comment':'oi'},'regras')

    def test_diagnostic_categories_cover_timeout_transport_http_auth_and_unknown(self):
        timeout=generation_error_diagnostics(TimeoutError('secret prompt body'),elapsed_ms=12.5)
        self.assertEqual((timeout['error_category'],timeout['stage'],timeout['elapsed_ms']),
                         ('TIMEOUT','provider_request',12.5))
        TransportError=type('ReadError',(Exception,),{'__module__':'httpx'})
        transport=generation_error_diagnostics(TransportError('private token'))
        self.assertEqual(transport['error_category'],'TRANSPORT')
        http_error=RuntimeError('sensitive response body');http_error.status_code=503
        service=generation_error_diagnostics(http_error)
        self.assertEqual((service['error_category'],service['http_status']),('SERVICE',503))
        auth_error=RuntimeError('sensitive');auth_error.status_code=403
        self.assertEqual(generation_error_diagnostics(auth_error)['error_category'],'AUTHENTICATION')
        unknown=generation_error_diagnostics(RuntimeError('do not store this'))
        self.assertEqual(unknown['error_category'],'INTERNAL')
        parser_error=generation_error_diagnostics(ValueError('V3_INTENT_INVALID'))
        self.assertEqual(parser_error['error_code'],'V3_INTENT_INVALID')
        unsafe_parser_error=generation_error_diagnostics(ValueError('private generated content'))
        self.assertIsNone(unsafe_parser_error['error_code'])
        self.assertNotIn('secret prompt body',repr(timeout))
        self.assertNotIn('private token',repr(transport))
        self.assertNotIn('sensitive',repr(service))
        self.assertNotIn('do not store this',repr(unknown))
        self.assertNotIn('private generated content',repr(unsafe_parser_error))

    def test_empty_and_malformed_responses_have_distinct_extraction_diagnostics(self):
        empty=LiteLLMTransport({},completion=lambda **_kwargs:SimpleNamespace(choices=[]))
        with self.assertRaises(ProviderDiagnosticError) as caught:
            empty.gemini_response('oi','Ana',(),False,False,'','regras',correlation_id='empty-1')
        details=generation_error_diagnostics(caught.exception)
        self.assertEqual((details['error_code'],details['error_category'],details['stage']),
                         ('EMPTY_CHOICES','EMPTY_RESPONSE','response_extraction'))
        malformed=LiteLLMTransport({},completion=lambda **_kwargs:SimpleNamespace(choices=object()))
        with self.assertRaises(ProviderDiagnosticError) as caught:
            malformed.gemini_response('oi','Ana',(),False,False,'','regras')
        details=generation_error_diagnostics(caught.exception)
        self.assertEqual((details['error_code'],details['error_category']),
                         ('RESPONSE_SHAPE_INVALID','RESPONSE_EXTRACTION'))

    def test_timeout_budget_is_clamped_to_the_configured_deadline(self):
        self.assertEqual(LiteLLMTransport._timeout(3,12),3)
        self.assertEqual(LiteLLMTransport._timeout(100,12),12)
        self.assertEqual(LiteLLMTransport._timeout(-5,12),0.1)

    def test_local_timeout_matches_the_presenter_generation_budget(self):
        transport=LiteLLMTransport({'timeout':90},completion=lambda **_kwargs:result('Resposta local.'))
        self.assertEqual(transport.local_timeout,14.0)
        self.assertEqual(transport._timeout(14.0,min(transport.local_timeout,90.0)),14.0)

    def test_presenter_applies_its_local_token_timeout_and_keepalive_limits_to_litellm(self):
        calls=[]
        transport=LiteLLMTransport({'url':'http://127.0.0.1:11434/api/generate',
            'model':'qwen3:1.7b','timeout':90,'num_predict':110,'think':False},
            completion=lambda **kwargs:(calls.append(kwargs) or result('Resposta local.')))
        ZukoPresenter._apply_local_runtime_limits(transport,{'timeout':14,'num_predict':56,
            'keep_alive':'120s','model':'qwen3:1.7b','think':False})
        transport.local_response({'comment':'pergunta'},'regras',timeout=14)
        self.assertEqual(calls[0]['timeout'],14)
        self.assertEqual(calls[0]['max_tokens'],56)
        self.assertIs(calls[0]['think'],False)
        self.assertEqual(calls[0]['keep_alive'],'120s')
        self.assertEqual(transport.local_config['keep_alive'],'120s')

    def test_async_call_is_cancelled_without_waiting_for_timeout(self):
        async def slow_completion(**_kwargs):
            await asyncio.sleep(2)
            return result('resposta atrasada')
        cancelled=threading.Event()
        timer=threading.Timer(.05,cancelled.set)
        timer.start()
        transport=LiteLLMTransport({},async_completion=slow_completion)
        started=time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                transport.gemini_response('oi','Ana',(),False,False,'','regras',
                    timeout=1,cancelled=cancelled.is_set)
        finally:
            timer.join()
        self.assertLess(time.monotonic()-started,.5)

    def test_zuko_local_ai_uses_litellm_transport_and_existing_output_guard(self):
        class LocalTransport:
            def __init__(self):self.request=None
            def local_response(self,data,system,**kwargs):
                self.request=(data,system,kwargs)
                return 'Uma resposta nova acompanha a pergunta.'
        config=json.loads((Path(__file__).resolve().parents[1]/'zuko_personality.json').read_text(encoding='utf-8'))
        transport=LocalTransport()
        ai=ZukoAI(config,transport=transport)
        event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Ana',text='Como começo?',
            gift_type='',generation_context='somente contexto',recent_context=[],recent_speech=[],
            provider_timeout_seconds=1.5,provider_cancelled=lambda:False,correlation_id='c-local')
        text,provider=ai.response(event)
        self.assertEqual(provider,'OLLAMA_LOCAL')
        self.assertIn('Gere uma fala original com IA',transport.request[1])
        self.assertEqual(transport.request[2]['correlation_id'],'c-local')
        self.assertEqual(transport.request[2]['timeout'],1.5)
        self.assertEqual(transport.request[0]['viewer'],'Ana')
        self.assertEqual(text,'Uma resposta nova acompanha a pergunta.')


if __name__=='__main__':
    unittest.main()
