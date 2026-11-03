import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'npc_runtime'))

import gemini_model_settings as settings
from zuko_litellm import LiteLLMTransport
from zuko_presenter import ZukoPresenter


TEST_TMP_ROOT=Path(__file__).resolve().parent/'.gemini_selector_test_tmp'


def temporary_directory():
    TEST_TMP_ROOT.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT)


def response(text='Resposta simulada.'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class GeminiModelSettingsTests(unittest.TestCase):
    def test_catalog_has_official_ids_and_preferred_38(self):
        self.assertEqual(settings.PREFERRED_MODEL,'gemini-3.8-flash')
        self.assertEqual(settings.ID_BY_LABEL['Gemini 3.1 Pro (prévia)'],'gemini-3.1-pro-preview')
        self.assertEqual(settings.validate_model_id('gemini-3.6-flash'),'gemini-3.6-flash')
        with self.assertRaisesRegex(ValueError,'GEMINI_MODEL_UNSUPPORTED'):
            settings.validate_model_id('Gemini 3.8 Flash')

    def test_selection_persists_and_restores_after_restart(self):
        with temporary_directory() as folder:
            path=Path(folder)/'model.json'
            initial=settings.load('gemini-2.5-flash-lite',path=path)
            self.assertEqual(initial['configured_model'],'gemini-2.5-flash-lite')
            self.assertEqual(initial['selected_model'],settings.PREFERRED_MODEL)
            saved=settings.apply('gemini-3.8-flash',initial,path=path)
            reloaded=settings.load('gemini-2.5-flash-lite',path=path)
            self.assertEqual(reloaded['configured_model'],'gemini-3.8-flash')
            self.assertEqual(reloaded['previous_model'],'gemini-2.5-flash-lite')
            self.assertEqual(reloaded['last_changed_at'],saved['last_changed_at'])
            self.assertEqual(reloaded['status'],'AGUARDANDO_AUTORIZACAO')

    def test_invalid_saved_id_is_visible_and_does_not_replace_current_model(self):
        with temporary_directory() as folder:
            path=Path(folder)/'model.json'
            path.write_text(json.dumps({'configured_model':'gemini-model-made-up'}),encoding='utf-8')
            state=settings.load('gemini-2.5-flash-lite',path=path)
        self.assertEqual(state['configured_model'],'gemini-2.5-flash-lite')
        self.assertEqual(state['status'],'ERRO_CONFIGURACAO')
        self.assertEqual(state['settings_error'],'GEMINI_MODEL_SETTINGS_INVALID')

    def test_apply_updates_presenter_transport_and_ai_config_without_api_call(self):
        with temporary_directory() as folder:
            path=Path(folder)/'model.json'
            state=settings.load('gemini-2.5-flash-lite',path=path)
            presenter=ZukoPresenter.__new__(ZukoPresenter)
            presenter.gemini_model_state=state
            presenter.config={'gemini':{'model':'gemini-2.5-flash-lite'},'local_ai':{'model':'qwen3:1.7b'}}
            presenter.litellm=SimpleNamespace(gemini_model='gemini-2.5-flash-lite')
            presenter.ai=SimpleNamespace(config={'gemini':{'model':'gemini-2.5-flash-lite'}})
            presenter.provider_reason=''
            presenter.log=mock.Mock()
            presenter._refresh_provider_status=mock.Mock()
            with mock.patch.object(settings,'SETTINGS_PATH',path):
                result=presenter.apply_gemini_model('gemini-3.8-flash')
            self.assertTrue(result['ok'])
            self.assertEqual(presenter.litellm.gemini_model,'gemini-3.8-flash')
            self.assertEqual(presenter.ai.config['gemini']['model'],'gemini-3.8-flash')
            self.assertEqual(presenter.config['gemini']['model'],'gemini-3.8-flash')
            presenter.log.assert_called_once()

    def test_restoring_last_known_model_is_explicit_and_persistent(self):
        with temporary_directory() as folder:
            path=Path(folder)/'model.json'
            state=settings.load('gemini-2.5-flash-lite',path=path)
            settings.apply('gemini-3.8-flash',state,path=path)
            presenter=ZukoPresenter.__new__(ZukoPresenter)
            presenter.gemini_model_state=settings.load('gemini-2.5-flash-lite',path=path)
            presenter.config={'gemini':{'model':'gemini-3.8-flash'},'local_ai':{}}
            presenter.litellm=SimpleNamespace(gemini_model='gemini-3.8-flash')
            presenter.ai=SimpleNamespace(config={'gemini':{'model':'gemini-3.8-flash'}})
            presenter.provider_reason='';presenter.log=mock.Mock();presenter._refresh_provider_status=mock.Mock()
            with mock.patch.object(settings,'SETTINGS_PATH',path):
                result=presenter.restore_last_functional_gemini_model()
            self.assertTrue(result['ok'],result)
            self.assertEqual(presenter.litellm.gemini_model,'gemini-2.5-flash-lite')
            self.assertEqual(settings.load('gemini-2.5-flash-lite',path=path)['configured_model'],
                             'gemini-2.5-flash-lite')

    def test_definitive_unavailable_model_reverts_to_previous_functional_choice(self):
        with temporary_directory() as folder:
            path=Path(folder)/'model.json'
            state=settings.load('gemini-2.5-flash-lite',path=path)
            state=settings.apply('gemini-3.8-flash',state,path=path)
            presenter=ZukoPresenter.__new__(ZukoPresenter)
            presenter.gemini_model_state=state
            presenter.litellm=SimpleNamespace(gemini_model='gemini-3.8-flash')
            presenter.config={'gemini':{'model':'gemini-3.8-flash'}}
            presenter.ai=SimpleNamespace(config={'gemini':{'model':'gemini-3.8-flash'}})
            presenter.monitor=SimpleNamespace(_log=mock.Mock())
            presenter.log=mock.Mock()
            class MissingModel(Exception):
                status_code=404
            unit=SimpleNamespace(metadata={'zuko_model':'gemini-3.8-flash'})
            with mock.patch.object(settings,'SETTINGS_PATH',path):
                presenter._record_gemini_error(MissingModel(),unit,'cid-test',0,'provider_request')
            self.assertEqual(presenter.litellm.gemini_model,'gemini-2.5-flash-lite')
            self.assertEqual(presenter.ai.config['gemini']['model'],'gemini-2.5-flash-lite')
            saved=settings.load('gemini-2.5-flash-lite',path=path)
            self.assertEqual(saved['configured_model'],'gemini-2.5-flash-lite')
            self.assertEqual(saved['last_error']['model'],'gemini-3.8-flash')
            presenter.log.assert_any_call('GEMINI_MODEL_ROLLBACK',rejected_model='gemini-3.8-flash',
                active_model='gemini-2.5-flash-lite',correlation_id='cid-test',http_status=404,error_code=None)

    def test_transient_timeout_does_not_change_configured_model(self):
        presenter=ZukoPresenter.__new__(ZukoPresenter)
        presenter.gemini_model_state={'configured_model':'gemini-3.8-flash',
            'selected_model':'gemini-3.8-flash','previous_model':'gemini-2.5-flash-lite',
            'last_successful_model':'gemini-2.5-flash-lite'}
        presenter.litellm=SimpleNamespace(gemini_model='gemini-3.8-flash')
        presenter.config={'gemini':{'model':'gemini-3.8-flash'}}
        presenter.ai=SimpleNamespace(config={'gemini':{'model':'gemini-3.8-flash'}})
        presenter.monitor=SimpleNamespace(_log=mock.Mock())
        presenter.log=mock.Mock()
        unit=SimpleNamespace(metadata={'zuko_model':'gemini-3.8-flash'})
        with temporary_directory() as folder:
            with mock.patch.object(settings,'SETTINGS_PATH',Path(folder)/'transient_model.json'):
                presenter._record_gemini_error(TimeoutError(),unit,'cid-timeout',0,'provider_request')
        self.assertEqual(presenter.litellm.gemini_model,'gemini-3.8-flash')
        self.assertNotIn('GEMINI_MODEL_ROLLBACK',[call.args[0] for call in presenter.log.call_args_list])

    def test_gemini_38_routes_to_ai_studio_without_vertex_or_unsupported_sampling(self):
        calls=[]
        def fake_completion(**kwargs):
            calls.append(kwargs)
            return response()
        transport=LiteLLMTransport({},gemini_model='gemini-3.8-flash',
            gemini_provider='gemini',completion=fake_completion)
        result_text=transport.gemini_response('Oi','Ana',(),False,False,'','instrução',timeout=2)
        self.assertEqual(result_text,'Resposta simulada.')
        call=calls[0]
        self.assertEqual(call['model'],'gemini/gemini-3.8-flash')
        self.assertNotIn('vertex_project',call)
        self.assertNotIn('vertex_location',call)
        self.assertNotIn('temperature',call)
        self.assertNotIn('api_key',call)

    def test_25_route_keeps_legacy_sampling_and_vertex_is_separate(self):
        calls=[]
        def fake_completion(**kwargs):
            calls.append(kwargs)
            return response()
        transport=LiteLLMTransport({},gemini_model='gemini-2.5-flash-lite',
            gemini_provider='gemini',completion=fake_completion)
        transport.gemini_response('Oi','Ana',(),False,False,'','instrução',timeout=2)
        self.assertEqual(calls[0]['model'],'gemini/gemini-2.5-flash-lite')
        self.assertEqual(calls[0]['temperature'],0.3)

    def test_ollama_is_blocked_by_default_until_explicit_operator_action(self):
        presenter=ZukoPresenter.__new__(ZukoPresenter)
        presenter.ollama_enabled=False
        presenter.config={'local_ai':{'model':'qwen3:1.7b'}}
        presenter.lock=__import__('threading').RLock()
        presenter.ollama_circuit_until=0
        presenter.log=mock.Mock()
        presenter.ai=SimpleNamespace(response=mock.Mock(side_effect=AssertionError('must stay disabled')))
        unit=SimpleNamespace(metadata={},unit_id='offline-unit')
        result=presenter._run_local_generation(SimpleNamespace(),unit,1,'TEST')
        self.assertEqual(result,(None,'AI_UNAVAILABLE',0.0))
        presenter.ai.response.assert_not_called()
        self.assertEqual(unit.metadata['zuko_outcome_reason'],'LOCAL_AI_DISABLED')


if __name__=='__main__':
    unittest.main()
