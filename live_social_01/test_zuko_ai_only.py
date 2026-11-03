import sys
import threading
import time
import unittest
import tempfile
from collections import Counter, OrderedDict
from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'npc_runtime'))

from live_response import LiveResponse
from zuko_conversation import Conversation
from live_director import DirectorUnit, LiveDirectorManager
from zuko_presenter import GeminiSessionBudget, GenerationCancelled, ZukoAI, ZukoPresenter
from zuko_litellm import ProviderDiagnosticError
from zuko_litellm import LiteLLMTransport
from live_logger import SessionLogger
from tts_manager import TTSManager
import zuko_voice_config


class FakeAI:
    def __init__(self, text='Resposta nova gerada pelo modelo.', error=None):
        self.text = text
        self.error = error
        self.events = []

    def response(self, event):
        self.events.append(event)
        if self.error:
            raise RuntimeError(self.error)
        return self.text, 'OLLAMA_LOCAL'

    @staticmethod
    def format_text(text):
        return str(text or '').strip()


class FakeGemini:
    def __init__(self, error=None, text='Resposta nova do Gemini.'):
        self.error = error
        self.text = text
        self.calls = 0
        self.requests = []

    def generate(self, *args):
        self.calls += 1
        self.requests.append(args)
        if self.error:
            raise RuntimeError(self.error)
        return self.text


class FakeLiteLLM:
    def __init__(self,error=None,text='Resposta nova do Gemini.'):
        self.error=error;self.text=text;self.calls=0;self.requests=[]
    def gemini_response(self,*args,**kwargs):
        self.calls+=1;self.requests.append((args,kwargs))
        if self.error:
            if isinstance(self.error,BaseException):raise self.error
            raise RuntimeError(self.error)
        return self.text


class FakeDirector:
    def __init__(self, epoch=0):
        self.epoch = epoch
        self.paused = False
        self.closed = False
        self.pending_units = []
        self.active_unit = None

    def before_tts(self, _unit_id):
        return True


class FakeNPC:
    state = 'ACTIVE'

    def __init__(self):
        self.events = []

    def event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class FakeMonitor:
    def __init__(self, real=False):
        self.paused = False
        self.session_epoch = 0
        self.source = 'tiktok' if real else 'tiktok-sim'
        self.local_test_mode = not real
        self.reading = real
        self.tiktok_source = SimpleNamespace(name='TIKTOKLIVE' if real else 'TIKTOK_SIMULATOR')
        self.root = SimpleNamespace(after=lambda *_args, **_kwargs: None)
        self.npc = FakeNPC()
        self.director = FakeDirector()
        self.presenter = SimpleNamespace(engagement=SimpleNamespace(
            question_window=SimpleNamespace(match=lambda _text: None),
            producer=SimpleNamespace(state=SimpleNamespace(current_topic='geral'))))
        self.session_memory = SimpleNamespace(recap=lambda: {'topics': ['geral'], 'events': {}})
        self.voice = SimpleNamespace(cancel_current=lambda **_kwargs: None, set_paused=lambda *_args: None)
        self.dashboard = SimpleNamespace(presenter_mode=SimpleNamespace(set=lambda _value: None))
        self.queued = []
        self.diagnostic_logs = []
        self.generator = SimpleNamespace(gemini=FakeGemini(),
            conversation_inputs=lambda *_args: ((), False, False, 'contexto global simulado', False))

    def _queue(self, response):
        self.queued.append(response)

    def _log(self, text):
        self.diagnostic_logs.append(text)


class ZukoAIOnlyTests(unittest.TestCase):
    def make_presenter(self, *, ai=None, real=False):
        monitor = FakeMonitor(real=real)
        presenter = ZukoPresenter.__new__(ZukoPresenter)
        presenter.monitor = monitor
        presenter.ai = ai or FakeAI()
        presenter.litellm = FakeLiteLLM()
        import json
        presenter.config = json.loads((PROJECT / 'zuko_personality.json').read_text(encoding='utf-8'))
        presenter.conversation = Conversation()
        presenter.gemini_budget = GeminiSessionBudget(max_calls=5, min_interval=0)
        presenter.gemini_budget.reset(0)
        presenter.stats = Counter()
        presenter.provider_reason = ''
        presenter.ollama_enabled = True  # Tests using local fallback opt in explicitly.
        presenter.active_provider = 'Aguardando resposta'
        presenter.active_model = '—'
        presenter.selected_ids = OrderedDict()
        presenter.deliveries = OrderedDict()
        presenter.inputs = OrderedDict()
        presenter.lock = threading.RLock()
        presenter.inference_lock = threading.Lock()
        presenter.generation_budget = 1.5
        presenter.auto = False
        presenter.paused = False
        presenter.closed = False
        presenter.epoch = 0
        presenter.last_activity = time.monotonic()
        presenter.last_auto = 0
        presenter.auto_times = []
        presenter.greeted = False
        presenter.last_comment = 0
        presenter.last_reply = ''
        presenter.history = []
        presenter.log = lambda event, **data: presenter.history.append({'event': event, **data})
        return presenter

    @staticmethod
    def unit(ident, *, source='AUDIENCE', content=None, event_type='CHAT', metadata=None):
        now = time.monotonic()
        return SimpleNamespace(unit_id=ident, source=source, event_type=event_type,
            metadata={'epoch': 0, **(metadata or {})}, created_at=now, ttl=10,
            priority=1, requires_tts=True, content_ref=content)

    def add_comment(self, presenter, ident, author, text):
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name=author,
            author_key=author.casefold(), text=text, gift_type='', source='TIKTOK',
            received_at=time.monotonic())
        presenter.inputs = {ident: event}
        presenter.dispatch(self.unit(ident, content=SimpleNamespace(author=author, text=text)))
        return event

    def test_contextual_followup_keeps_same_participant_history(self):
        presenter = self.make_presenter()
        earlier = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana-id', text='Estou montando um jogo em Python.')
        presenter.conversation.delivered(earlier, 'Qual parte do jogo você está fazendo?')
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana-id', text='E isso funciona no celular?')
        self.assertTrue(presenter.conversation.requires_context_understanding(event))
        presenter._response_bounded(event, self.unit('followup'), 0)
        seen = presenter.ai.events[-1]
        self.assertEqual(seen.recent_context[0]['comment'], earlier.text)
        self.assertEqual(seen.recent_speech[0]['spoken_reply'], 'Qual parte do jogo você está fazendo?')
        self.assertEqual(seen.generation_context['live_topic'], 'geral')
        self.assertEqual(seen.generation_context['session_recap']['topics'], ['geral'])

    def test_participant_contexts_are_separate_but_public_context_is_shared(self):
        conversation = Conversation()
        conversation.delivered(SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana', text='Meu projeto é um jogo.'), 'Você está usando Python?')
        conversation.delivered(SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Bia',
            author_key='bia', text='Estou aprendendo música.'), 'Qual instrumento você escolheu?')
        self.assertEqual(len(conversation.context(SimpleNamespace(author_key='ana', author_name='Ana'))), 1)
        self.assertEqual(len(conversation.context(SimpleNamespace(author_key='bia', author_name='Bia'))), 1)
        self.assertEqual(conversation.context(SimpleNamespace(author_key='cai', author_name='Caio')), [])
        self.assertEqual(len(conversation.recent_public_context()), 2)

    def test_greeting_uses_local_ai_and_preserves_single_queue_and_movement_route(self):
        presenter = self.make_presenter(ai=FakeAI('Bom dia, Ana! Como começou seu projeto?'))
        event = self.add_comment(presenter, 'greeting', 'Ana', 'Oi ZUKO')
        self.assertEqual(len(presenter.monitor.queued), 1)
        queued = presenter.monitor.queued[0]
        self.assertEqual(queued.provider, 'ZUKO_OLLAMA_LOCAL')
        self.assertEqual(presenter.monitor.npc.events[0][0][1], 'comment')
        self.assertEqual(presenter.stats['ZUKO_RULE_TEXTS'], 0)
        self.assertEqual(presenter.ai.events[-1].text, event.text)

    def test_authorized_gemini_failure_falls_back_to_local_without_bypassing_budget(self):
        presenter = self.make_presenter(ai=FakeAI('A resposta local acompanha o assunto.'),
                                        real=True)
        presenter.gemini_budget.reset(0)
        self.assertEqual(presenter.gemini_budget.authorize(3, 0), (True, 'authorized'))
        presenter.litellm = FakeLiteLLM(error='simulated unavailable')
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana', text='Como funciona esse desenho?', gift_type='',
            source='TIKTOK', received_at=time.monotonic())
        presenter.inputs = {'question': event}
        presenter.dispatch(self.unit('question', content=SimpleNamespace(author='Ana', text=event.text)))
        self.assertEqual(presenter.litellm.calls, 1)
        self.assertEqual(presenter.monitor.queued[0].provider, 'ZUKO_OLLAMA_LOCAL')
        state = presenter.gemini_budget.snapshot(0)
        self.assertEqual((state['used'], state['remaining'], state['authorized']), (1, 2, True))
        self.assertTrue(any(row.get('fallback') == 'OLLAMA_LOCAL' for row in presenter.history))

    def test_authorized_gemini_is_primary_when_it_succeeds(self):
        presenter = self.make_presenter(ai=FakeAI('Esta resposta local não deve ser usada.'),
                                        real=True)
        presenter.gemini_budget.reset(0)
        presenter.gemini_budget.authorize(3, 0)
        presenter.litellm = FakeLiteLLM(text='A resposta do Gemini acompanha sua pergunta.')
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana', text='Como funciona esse desenho?', gift_type='',
            source='TIKTOK', received_at=time.monotonic())
        presenter.inputs = {'gemini-primary': event}
        presenter.dispatch(self.unit('gemini-primary',
            content=SimpleNamespace(author='Ana', text=event.text)))
        self.assertEqual(presenter.monitor.queued[0].provider, 'ZUKO_GEMINI')
        self.assertEqual(presenter.litellm.calls, 1)
        self.assertEqual(presenter.ai.events, [])
        self.assertEqual(presenter.gemini_budget.snapshot(0)['used'], 1)
        self.assertIn('Você é ZUKO', presenter.litellm.requests[0][0][-1])

    def test_presenter_formatter_preserves_unicode_punctuation_and_speech_dashes(self):
        cases = (
            'A manutenção da caldeira está estável?',
            'Que legal! A IA prevê falhas — e reduz paradas.',
            'Zuko: explique a pressão da caldeira, por favor!',
            'Os sensores térmicos, elétricos e mecânicos estão ativos.',
            'Ação, coração, açúcar e programação: tudo certo! 😊🚀',
            'Tecnologia 👩‍💻, ciência e diversão para vocês! ✨',
        )
        for original in cases:
            with self.subTest(text=original):
                expected = original if original[-1] in '.!?' else original + '.'
                formatted = ZukoAI.format_text(original)
                self.assertEqual(formatted, expected)
                self.assertNotIn('\ufffd', formatted)

    def test_litellm_presenter_and_voice_queue_preserve_portuguese_unicode(self):
        answer = 'Ação, coração, açúcar e programação: tudo certo! 😊🚀'
        transport = LiteLLMTransport({}, completion=lambda **_kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]),
            gemini_model='gemini-3.8-flash', gemini_provider='gemini')
        self.assertEqual(transport.gemini_response('Diga oi', 'Ana', (), False, False,
            '', 'Responda em pt-BR.'), answer)

        presenter = self.make_presenter(ai=FakeAI(), real=True)
        presenter.ai.format_text = ZukoAI.format_text
        presenter.gemini_budget.reset(0)
        presenter.gemini_budget.authorize(1, 0)
        presenter.litellm = FakeLiteLLM(text=answer)
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana-unicode', text='Como está?', gift_type='', source='TIKTOK',
            received_at=time.monotonic())
        presenter.inputs = {'unicode': event}
        presenter.dispatch(self.unit('unicode', content=SimpleNamespace(author='Ana', text='Como está?'),
            metadata={'correlation_id': 'corr-unicode'}))
        response = presenter.monitor.queued[0]
        self.assertEqual(response.text, answer + '.')
        voice_queue = TTSManager(lambda *_args: None, lambda *_args: None)
        voice_queue.worker = SimpleNamespace(is_alive=lambda: True)  # No synthesis/playback in this test.
        voice_queue.enqueue(response)
        self.assertEqual(voice_queue.queue[0].response.text, answer + '.')

    def test_utf8_session_log_round_trip_keeps_accents_cedilla_and_emoji(self):
        message = 'Ação, coração, açúcar, ç e programação 😊🚀'
        with tempfile.TemporaryDirectory() as directory:
            logger = SessionLogger(Path(directory))
            logger.write('Presenter', message)
            import json
            row = json.loads(logger.path.read_text(encoding='utf-8'))
        self.assertEqual(row['event'], message)

    def test_ollama_response_uses_same_fixed_presenter_formatter(self):
        presenter = self.make_presenter()

        class LocalTransport:
            def local_response(self, *_args, **_kwargs):
                return 'A caldeira está estável — os sensores registram pressão normal.'

        ai = ZukoAI(presenter.config, transport=LocalTransport())
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana', text='Como está a caldeira?', gift_type='',
            source='LOCAL_TEST', received_at=time.monotonic(), correlation_id='corr-ollama')
        text, provider = ai.response(event)
        self.assertEqual(provider, 'OLLAMA_LOCAL')
        self.assertEqual(text, 'A caldeira está estável — os sensores registram pressão normal.')

    def test_formatted_gemini_text_reaches_tts_ok_and_then_memory(self):
        presenter = self.make_presenter(ai=FakeAI(), real=True)
        presenter.ai.format_text = ZukoAI.format_text
        presenter.gemini_budget.reset(0)
        presenter.gemini_budget.authorize(1, 0)
        answer = 'A IA analisa a caldeira — e identifica variações de pressão.'
        presenter.litellm = FakeLiteLLM(text=answer)
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana-id', text='Como a IA ajuda nessa caldeira?', gift_type='',
            source='TIKTOK', received_at=time.monotonic())
        presenter.inputs = {'formatter-pipeline': event}
        presenter.dispatch(self.unit('formatter-pipeline',
            content=SimpleNamespace(author='Ana', text=event.text),
            metadata={'correlation_id': 'corr-format-pipeline'}))

        self.assertEqual(len(presenter.monitor.queued), 1)
        response = presenter.monitor.queued[0]
        self.assertEqual(response.text, answer)
        self.assertEqual(response.provider, 'ZUKO_GEMINI')
        self.assertIn(response.comment_id, presenter.deliveries)
        presenter.tts_result('TTS_OK', response)
        self.assertEqual(presenter.conversation.context(event), [
            {'comment': event.text, 'spoken_reply': answer}])
        self.assertEqual(presenter.history[-1]['event'], 'TTS_DELIVERY_RESULT')
        self.assertEqual(presenter.history[-1]['outcome'], 'TTS_OK')

    def test_unlimited_saved_without_authorization_uses_local_without_mutating_budget(self):
        presenter = self.make_presenter(ai=FakeAI('Resposta local simulada.'))
        tts_before = zuko_voice_config.authorization_status().copy()
        self.assertEqual(presenter.gemini_budget.set_limit(None, 0), (True, 'saved'))
        before = presenter.gemini_budget.snapshot(0).copy()
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana', text='Oi', gift_type='', source='TIKTOK',
            received_at=time.monotonic())
        text, provider = presenter._response_bounded(event, self.unit('unlimited'), 0)
        after = presenter.gemini_budget.snapshot(0)
        self.assertEqual((text, provider), ('Resposta local simulada.', 'OLLAMA_LOCAL'))
        self.assertEqual(before, after)
        self.assertFalse(after['authorized'])
        self.assertEqual(presenter.litellm.calls, 0)
        self.assertEqual(zuko_voice_config.authorization_status(), tts_before)

    def test_no_ready_fallback_when_both_ai_engines_are_unavailable(self):
        presenter = self.make_presenter(ai=FakeAI(error='local offline'), real=True)
        presenter.gemini_budget.reset(0)
        presenter.gemini_budget.authorize(2, 0)
        presenter.litellm = FakeLiteLLM(error='Gemini simulated failure')
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana',
            author_key='ana', text='O que você achou?', gift_type='',
            source='TIKTOK', received_at=time.monotonic())
        presenter.inputs = {'offline': event}
        presenter.dispatch(self.unit('offline', content=SimpleNamespace(author='Ana', text=event.text)))
        self.assertEqual(presenter.monitor.queued, [])
        self.assertEqual(presenter.stats['ZUKO_RULE_TEXTS'], 0)
        self.assertTrue(any(row.get('event') == 'AI_SPEECH_SUPPRESSED' for row in presenter.history))
        failure_presenter = self.make_presenter(ai=FakeAI(error='local offline'))
        unit = self.unit('offline', metadata={'correlation_id': 'corr-offline'})
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana', author_key='ana',
            text='O que você achou?', gift_type='', source='TIKTOK', received_at=time.monotonic())
        failure_presenter.inputs = {'offline': event}
        failure_presenter.dispatch(unit)
        self.assertEqual(unit.metadata['zuko_dispatch_outcome'], 'AI_UNAVAILABLE')
        self.assertEqual(unit.metadata['zuko_outcome_reason'], 'PROVIDER_ERROR:RuntimeError')
        self.assertFalse(failure_presenter.monitor.queued)

    def test_gemini_provider_error_is_classified_correlated_and_visible_without_message(self):
        presenter=self.make_presenter(ai=FakeAI(error='local offline'),real=True)
        presenter.gemini_budget.reset(0);presenter.gemini_budget.authorize(1,0)
        error=RuntimeError('secret prompt and credential-like text')
        error.status_code=503
        presenter.litellm=FakeLiteLLM(error=error)
        event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Ana',author_key='ana',
            text='Pergunta controlada',gift_type='',source='TIKTOK',received_at=time.monotonic())
        presenter.inputs={'diag-provider':event}
        unit=self.unit('diag-provider',metadata={'correlation_id':'corr-diagnostic-503'})
        with tempfile.TemporaryDirectory() as tempdir:
            presenter.trace_path=Path(tempdir)/'zuko.jsonl'
            presenter.log=ZukoPresenter.log.__get__(presenter,ZukoPresenter)
            presenter.dispatch(unit)
            row=next(row for row in presenter.history if row.get('event')=='AI_PROVIDER_ERROR')
            self.assertEqual(row['route'],'GEMINI_LITELLM')
            self.assertEqual(row['model'],'gemini-2.5-flash-lite')
            self.assertEqual(row['correlation_id'],'corr-diagnostic-503')
            self.assertEqual((row['error_category'],row['http_status'],row['stage']),
                             ('SERVICE',503,'provider_request'))
            self.assertGreaterEqual(row['elapsed_ms'],0)
            self.assertNotIn('secret prompt',repr(row))
            gemini_dashboard_line=next(line for line in presenter.monitor.diagnostic_logs
                                       if line.startswith('GEMINI_DIAGNOSTIC_ERROR'))
            self.assertIn('correlation_id=corr-diagnostic-503',gemini_dashboard_line)
            self.assertIn('category=SERVICE',gemini_dashboard_line)
            self.assertIn('Gemini SERVICE',presenter.provider_reason)
            self.assertNotEqual(unit.metadata.get('zuko_outcome_reason'),'NO_GENERATED_OUTPUT')

    def test_empty_provider_reply_is_not_reported_as_unknown_or_generated_output(self):
        presenter=self.make_presenter(ai=FakeAI(error='local offline'),real=True)
        presenter.gemini_budget.reset(0);presenter.gemini_budget.authorize(1,0)
        presenter.litellm=FakeLiteLLM(error=ProviderDiagnosticError(
            'EMPTY_CONTENT','EMPTY_RESPONSE','response_extraction'))
        event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Ana',author_key='ana',
            text='Pergunta controlada',gift_type='',source='TIKTOK',received_at=time.monotonic())
        presenter.inputs={'diag-empty':event}
        unit=self.unit('diag-empty',metadata={'correlation_id':'corr-empty-response'})
        presenter.dispatch(unit)
        row=next(row for row in presenter.history if row.get('event')=='AI_PROVIDER_ERROR')
        self.assertEqual((row['error_code'],row['error_category'],row['stage']),
                         ('EMPTY_CONTENT','EMPTY_RESPONSE','response_extraction'))
        self.assertEqual(row['correlation_id'],'corr-empty-response')
        self.assertNotEqual(unit.metadata.get('zuko_outcome_reason'),'NO_GENERATED_OUTPUT')

    def test_truncated_gemini_reply_is_logged_and_never_enqueued_for_tts(self):
        metadata={'model':'gemini-3.8-flash','finish_reason':'length',
            'native_finish_reason':'MAX_TOKENS','prompt_tokens':124,
            'completion_tokens':512,'total_tokens':636,'reasoning_tokens':252,'elapsed_ms':8000.0}
        presenter=self.make_presenter(ai=FakeAI(error='local disabled'),real=True)
        presenter.ollama_enabled=False
        presenter.gemini_budget.reset(0);presenter.gemini_budget.authorize(1,0)
        presenter.litellm=FakeLiteLLM(error=ProviderDiagnosticError(
            'GEMINI_OUTPUT_TRUNCATED','TRUNCATED','provider_response',response_metadata=metadata))
        presenter.litellm.gemini_model='gemini-3.8-flash'
        event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Ana',author_key='ana',
            text='Pode cumprimentar o chat?',gift_type='',source='TIKTOK',received_at=time.monotonic())
        presenter.inputs={'truncated':event}
        unit=self.unit('truncated',metadata={'correlation_id':'corr-truncated'})
        with tempfile.TemporaryDirectory() as tempdir:
            presenter.trace_path=Path(tempdir)/'zuko.jsonl'
            presenter.log=ZukoPresenter.log.__get__(presenter,ZukoPresenter)
            presenter.dispatch(unit)
            self.assertEqual(presenter.monitor.queued,[])
            self.assertEqual(presenter.ai.events,[])
            self.assertEqual(unit.metadata['zuko_gemini_response']['finish_reason'],'length')
            self.assertEqual(presenter.stats['ZUKO_GEMINI_TRUNCATED'],1)
            truncated=next(row for row in presenter.history if row.get('event')=='AI_GENERATION_TRUNCATED')
            self.assertEqual(truncated['native_finish_reason'],'MAX_TOKENS')
            self.assertEqual(truncated['reasoning_tokens'],252)
            error=next(row for row in presenter.history if row.get('event')=='AI_PROVIDER_ERROR')
            self.assertEqual(error['error_code'],'GEMINI_OUTPUT_TRUNCATED')

    def test_director_complete_reports_silent_dispatch_outcome_and_correlation(self):
        def failed_generation(unit):
            unit.metadata.update(zuko_dispatch_outcome='AI_UNAVAILABLE',
                                 zuko_outcome_reason='PROVIDER_TIMEOUT')
        director = LiveDirectorManager(failed_generation, tts_snapshot=lambda: {})
        unit = DirectorUnit('unit-1', 'LOCAL', 'participant-1', metadata={'correlation_id': 'corr-1'})
        self.assertTrue(director.submit(unit))
        self.assertTrue(director.run_once())
        completion = next(row for row in director.drain_logs() if row.startswith('DIRECTOR_COMPLETE'))
        self.assertIn('correlation_id=corr-1', completion)
        self.assertIn('outcome=AI_UNAVAILABLE', completion)
        self.assertIn('outcome_reason=PROVIDER_TIMEOUT', completion)

    def test_cancelled_generation_is_not_reported_as_provider_timeout(self):
        class CancelledAI(FakeAI):
            def response(self, _event):
                raise GenerationCancelled('cancelled by caller')
        presenter = self.make_presenter(ai=CancelledAI())
        event = SimpleNamespace(event_type='CHAT_MESSAGE', author_name='Ana', author_key='ana',
            text='Como isso funciona?', gift_type='', source='LOCAL_TEST', received_at=time.monotonic())
        unit = self.unit('cancelled', metadata={'correlation_id': 'corr-cancelled'})
        presenter.inputs = {'cancelled': event}
        presenter.dispatch(unit)
        self.assertEqual(unit.metadata['zuko_dispatch_outcome'], 'CANCELLED')
        self.assertEqual(unit.metadata['zuko_outcome_reason'], 'GENERATION_CANCELLED')

    def test_autonomous_presentation_is_generated_instead_of_using_saved_script(self):
        presenter = self.make_presenter(ai=FakeAI('O papo está animado; qual foi a pequena vitória de vocês hoje?'))
        old_script = 'FALA PRONTA QUE NÃO DEVE SER ENFILEIRADA'
        content = LiveResponse('auto-1', '', old_script, 'ZUKO_AUTO_RULE', 0,
                               time.monotonic(), 'ZUKO', True)
        unit = self.unit('auto-1', source='PRESENTER', content=content,
                         metadata={'zuko_auto': True})
        presenter.dispatch(unit)
        self.assertEqual(presenter.ai.events[-1].event_type, 'PRESENTER_AUTONOMOUS')
        self.assertEqual(presenter.ai.events[-1].text, '')
        self.assertEqual(presenter.monitor.queued[0].text,
                         'O papo está animado; qual foi a pequena vitória de vocês hoje?')
        self.assertEqual(presenter.monitor.queued[0].provider, 'ZUKO_OLLAMA_LOCAL')
        self.assertEqual(presenter.stats['ZUKO_RULE_TEXTS'], 0)

    def test_gift_event_is_ai_worded_then_uses_the_existing_movement_and_queue_routes(self):
        presenter = self.make_presenter(ai=FakeAI('Muito obrigado pelo presente; você deixou o chat mais animado!'))
        event = SimpleNamespace(event_type='GIFT_EVENT', author_name='Bia',
            author_key='bia', text='', gift_type='Rosa', source='TIKTOK',
            received_at=time.monotonic())
        presenter.inputs = {'gift-id': event}
        unit = self.unit('event:gift-id', source='HIGH_EVENT', event_type='GIFT',
                         content=LiveResponse('event:gift-id', 'Bia', 'fala antiga', 'EVENT_RULE',
                                              0, event.received_at, 'LIVE_EVENT', True))
        presenter.dispatch(unit)
        self.assertEqual(presenter.ai.events[-1].event_type, 'GIFT_EVENT')
        self.assertEqual(presenter.ai.events[-1].gift_type, 'Rosa')
        self.assertEqual(presenter.monitor.npc.events[0][0][1], 'gift')
        self.assertEqual(len(presenter.monitor.queued), 1)
        self.assertEqual(presenter.monitor.queued[0].provider, 'ZUKO_OLLAMA_LOCAL')
        self.assertEqual(presenter.stats['ZUKO_RULE_TEXTS'], 0)

    def test_repeated_ai_reply_is_silenced_instead_of_replaced_by_a_template(self):
        presenter = self.make_presenter(ai=FakeAI('Resposta que já foi dita nesta LIVE.'))
        presenter.conversation.delivered(SimpleNamespace(event_type='CHAT_MESSAGE',
            author_name='Bia', author_key='bia', text='Comentário anterior.'),
            'Resposta que já foi dita nesta LIVE.')
        self.add_comment(presenter, 'repeat', 'Ana', 'Outro comentário válido.')
        self.assertEqual(presenter.monitor.queued, [])
        self.assertEqual(presenter.stats['ZUKO_RULE_TEXTS'], 0)


if __name__ == '__main__':
    unittest.main()
