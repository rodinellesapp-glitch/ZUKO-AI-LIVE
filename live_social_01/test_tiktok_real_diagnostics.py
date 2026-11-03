import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'npc_runtime'))

import httpx
from live_tiktok_real_source import (TikTokHTTPResponseError,TikTokRealEventSource,_lease,
    error_category,error_diagnostic,guard_json_response,parse_retry_after)
from live_tiktok_config import tiktok_room_id
from live_dashboard_v2 import LiveDashboardV2,connection_health_snapshot


class TikTokErrorDiagnosticsTests(unittest.TestCase):
    def malformed_response_error(self,status=200,content_type='text/html'):
        request=httpx.Request('GET','https://webcast.tiktok.com/api-live/user/room/?uniqueId=seu_canal&sessionid=secret-token')
        response=httpx.Response(status,headers={'content-type':content_type,'server':'edge-test','content-length':'35'},
            content=b'<html>challenge sessionid=secret-token</html>',request=request)
        def parse(response):return response.json()
        try:parse(response)
        except Exception as error:return error
        self.fail('response fixture must fail JSON parsing')

    def test_json_error_has_safe_trace_and_http_metadata_only(self):
        diagnostic=error_diagnostic(self.malformed_response_error())
        self.assertEqual(diagnostic['category'],'INVALID_RESPONSE')
        self.assertIn('response.json()',diagnostic['traceback'])
        self.assertEqual(diagnostic['responses'][0]['status'],200)
        self.assertEqual(diagnostic['responses'][0]['content_type'],'text/html')
        self.assertEqual(diagnostic['responses'][0]['host'],'webcast.tiktok.com')
        encoded=json.dumps(diagnostic)
        self.assertNotIn('secret-token',encoded)
        self.assertNotIn('challenge',encoded)
        self.assertNotIn('sessionid=',encoded)
        self.assertNotIn('uniqueId=',encoded)

    def test_http_status_separates_auth_and_rate_limit_from_invalid_json(self):
        self.assertEqual(error_category(self.malformed_response_error(401)), 'AUTH_REQUIRED')
        self.assertEqual(error_category(self.malformed_response_error(403)), 'ACCESS_RESTRICTED')
        self.assertEqual(error_category(self.malformed_response_error(429)), 'RATE_LIMITED')
        self.assertEqual(error_category(self.malformed_response_error(503)), 'SERVICE_ERROR')
        self.assertEqual(error_category(self.malformed_response_error(200)), 'INVALID_RESPONSE')
        self.assertEqual(error_category(ConnectionError('offline')), 'CONNECTION_FAILED')
        self.assertEqual(error_category(httpx.ConnectTimeout('timeout')), 'CONNECTION_FAILED')

    def test_traceback_redacts_bearer_credentials_if_exception_contains_them(self):
        diagnostic=error_diagnostic(RuntimeError('authorization: Bearer test-secret'))
        self.assertNotIn('test-secret',diagnostic['traceback'])

    def test_invalid_response_is_saved_and_does_not_trigger_reconnect_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            source=TikTokRealEventSource(diagnostic_directory=folder)
            attempts=[]
            def runner(_generation):
                attempts.append(1);source._error(self.malformed_response_error())
            source._session_runner=runner
            self.assertTrue(source.start());source._thread.join(3)
            self.assertFalse(source._thread.is_alive())
            health=source.health()
            self.assertEqual(health['connection'],'ERROR')
            self.assertEqual(health['reason'],'INVALID_RESPONSE')
            self.assertEqual(health['reconnect_attempts'],0)
            self.assertEqual(len(attempts),1)
            saved=json.loads(Path(health['diagnostic_file']).read_text(encoding='utf-8'))
            self.assertEqual(saved['responses'][0]['status'],200)
            self.assertNotIn('secret-token',json.dumps(saved))

    def test_legacy_dom_and_godot_tiktok_indicators_are_independent(self):
        monitor=SimpleNamespace(
            npc=SimpleNamespace(state='ACTIVE',presentation_status={'animation':'Walk'}),
            tiktok_source=SimpleNamespace(simulation=False,health=lambda:{'connection':'ERROR','reason':'INVALID_RESPONSE'}))
        result=connection_health_snapshot(monitor,{'DOM':'OFFLINE','PONTE 8766':'OFFLINE'})
        self.assertEqual(result['DOM'],'OFFLINE')
        self.assertEqual(result['PONTE 8766'],'OFFLINE')
        self.assertEqual(result['GODOT TCP 18765'],'MOVIMENTO CONFIRMADO · Walk')
        self.assertEqual(result['TIKTOKLIVE'],'DESCONECTADO · ERROR · INVALID_RESPONSE')
        text=LiveDashboardV2.tiktok_connection_text(monitor)
        self.assertIn('Desconectado',text)
        self.assertIn('INVALID_RESPONSE',text)

    def test_discovery_and_rate_limit_states_are_visibly_disconnected(self):
        for state,reason in (('ERROR','ROOM_DISCOVERY_FAILED'),('RATE_LIMITED','RATE_LIMITED')):
            monitor=SimpleNamespace(tiktok_source=SimpleNamespace(simulation=False,
                health=lambda state=state,reason=reason:{'connection':state,'reason':reason,'broadcaster':'@seu_canal'}))
            line=connection_health_snapshot(monitor,{})['TIKTOKLIVE']
            self.assertIn('DESCONECTADO',line)
            self.assertIn(reason,line)
            self.assertIn('Desconectado',LiveDashboardV2.tiktok_connection_text(monitor))

    def response(self,status=200,content_type='application/json',headers=None,path='/api-live/user/room/'):
        request=httpx.Request('GET','https://www.tiktok.com'+path)
        values={'content-type':content_type};values.update(headers or {})
        return httpx.Response(status,headers=values,content=b'{"data":{"room_id":"123"}}',request=request)

    @staticmethod
    def run_response_hook(response):
        # This hook contains no awaits; drive it directly so offline tests do
        # not need to initialize Windows' socket-backed asyncio wakeup pipe.
        coro=guard_json_response(response)
        try:coro.send(None)
        except StopIteration:return
        raise AssertionError('response guard unexpectedly suspended')

    def test_sdk_json_endpoint_guard_accepts_valid_json_and_never_parses_html_or_429(self):
        good=self.response()
        self.run_response_hook(good)
        self.assertEqual(good.json()['data']['room_id'],'123')
        for bad in (self.response(429,'text/html',{'retry-after':'17'}),self.response(200,'text/html')):
            with self.assertRaises(TikTokHTTPResponseError) as caught:
                self.run_response_hook(bad)
            self.assertIs(caught.exception.response,bad)
            self.assertNotIn(bad.text,str(caught.exception))
            if bad.status_code==429:
                diagnostic=error_diagnostic(caught.exception)
                self.assertEqual(diagnostic['category'],'RATE_LIMITED')
                self.assertEqual(diagnostic['responses'][0]['retry_after'],'17')
            else:self.assertEqual(error_category(caught.exception),'INVALID_RESPONSE')
        self.assertEqual(error_category(self.malformed_response_error(200,'text/html')),'INVALID_RESPONSE')

    def test_retry_after_seconds_and_http_date(self):
        self.assertEqual(parse_retry_after('17',1000),17.)
        self.assertEqual(parse_retry_after('bad',1000),None)
        self.assertEqual(parse_retry_after('Thu, 01 Jan 1970 00:17:00 GMT',1000),20.)

    def test_rate_limit_state_honors_retry_after_without_retrying_it(self):
        with tempfile.TemporaryDirectory() as folder:
            source=TikTokRealEventSource(diagnostic_directory=folder,clock=lambda:100.,wall_clock=lambda:1000.)
            source._error(TikTokHTTPResponseError(self.response(429,'text/html',{'retry-after':'17'})))
            self.assertEqual(source.health()['connection'],'RATE_LIMITED')
            self.assertEqual(source.health()['retry_after_seconds'],17.)
            self.assertFalse(source.start())
            self.assertEqual(source.health()['reason'],'RETRY_AFTER')
            self.assertEqual(source._reconnects,0)

    def test_offline_and_missing_sigi_are_distinct_and_not_auto_retried(self):
        class UserOfflineError(Exception):pass
        class FailedParseRoomIdError(Exception):pass
        self.assertEqual(error_category(UserOfflineError()),'LIVE_OFFLINE')
        self.assertEqual(error_category(FailedParseRoomIdError('SIGI_STATE absent')),'ROOM_DISCOVERY_FAILED')
        with tempfile.TemporaryDirectory() as folder:
            source=TikTokRealEventSource(diagnostic_directory=folder)
            attempts=[]
            source._session_runner=lambda _generation:(attempts.append(1),source._error(UserOfflineError()))
            self.assertTrue(source.start());source._thread.join(3)
            self.assertFalse(source._thread.is_alive())
            self.assertEqual(attempts,[1]);self.assertEqual(source.health()['reconnect_attempts'],0)

    def test_connection_retries_have_capped_exponential_backoff(self):
        source=TikTokRealEventSource()
        source._generation=1;attempts=[];delays=[]
        def failed_attempt(_generation):
            attempts.append(1);source._state='ERROR';source._reason='CONNECTION_FAILED'
        self.assertTrue(_lease.acquire(blocking=False))
        try:
            with patch.object(source._stopping,'wait',side_effect=lambda delay:(delays.append(delay) or False)):
                source._session_runner=failed_attempt
                source._run(1)
        finally:
            if _lease.locked():_lease.release()
        self.assertEqual(len(attempts),4)
        self.assertEqual(delays,[2,4,8])
        self.assertEqual(source.health()['reconnect_attempts'],3)

    def test_optional_room_id_requires_canonical_profile_origin_and_decimal_id(self):
        valid={'TIKTOK_ROOM_ID':'123456789','TIKTOK_ROOM_ID_SOURCE_URL':'https://www.tiktok.com/@seu_canal/live'}
        with patch.dict(os.environ,valid):self.assertEqual(tiktok_room_id('seu_canal'),123456789)
        invalid=[
            {'TIKTOK_ROOM_ID':'123','TIKTOK_ROOM_ID_SOURCE_URL':'http://www.tiktok.com/@seu_canal/live'},
            {'TIKTOK_ROOM_ID':'123','TIKTOK_ROOM_ID_SOURCE_URL':'https://evil.example/@seu_canal/live'},
            {'TIKTOK_ROOM_ID':'123','TIKTOK_ROOM_ID_SOURCE_URL':'https://www.tiktok.com/@someoneelse/live'},
            {'TIKTOK_ROOM_ID':'12x','TIKTOK_ROOM_ID_SOURCE_URL':'https://www.tiktok.com/@seu_canal/live'},
        ]
        for env in invalid:
            with self.subTest(env=env),patch.dict(os.environ,env):
                with self.assertRaises(ValueError):tiktok_room_id('seu_canal')

    def test_diagnostic_prefers_api_429_over_profile_html_200(self):
        self.assertEqual(error_category(RuntimeError('failed'),[
            {'status':429},{'status':200}]),'RATE_LIMITED')


if __name__=='__main__':unittest.main()
