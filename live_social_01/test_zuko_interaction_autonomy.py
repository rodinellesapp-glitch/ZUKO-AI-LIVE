"""Offline regressions for audience routing, custom autonomy topics and shuffle."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

from live_director import DirectorConfig, DirectorUnit, LiveDirectorManager
from live_audience import LiveAudienceManager, flow_priority
from live_flow import LiveFlowEngine
from live_platform_adapter import PlatformEvent
from zuko_soundtrack import DEFAULT, SoundtrackController, validate_preferences
from zuko_v3_content import ContentPlanner, build_system_prompt, load_config, salvage_audience_speech
from zuko_v3_engine import AutonomousEngine

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'npc_runtime'))
from live_dashboard_v2 import LiveDashboardV2, _zuko_metric_lines


class Clock:
    def __init__(self): self.now=100.
    def __call__(self): return self.now
    def advance(self,seconds): self.now+=seconds


def event(kind,ident,*,author='viewer-1',name='Visitante',text='',confirmed=True):
    return PlatformEvent('tiktok-sim',kind,ident,author,name,text,confirmed=confirmed)


class FirstChoice:
    @staticmethod
    def choice(values): return values[0]


class FakeMusicBackend:
    def __init__(self):self.path='';self.state='stopped';self.volume=0.
    def open(self,path):self.path=str(path);self.state='stopped'
    def play(self):self.state='playing'
    def pause(self):self.state='paused'
    def resume(self):self.state='playing'
    def mode(self):return self.state
    def set_volume(self,value):self.volume=value
    def close(self):self.path='';self.state='stopped'


class InteractionAutonomyTests(unittest.TestCase):
    def test_custom_theme_stays_pinned_across_plans_and_interruptions(self):
        planner=ContentPlanner();mode=load_config()['modes']['NORMAL'];planner.suggest_topic('Cultura pop e jogos')
        plans=[];now=100.
        for index in range(12):
            plan=planner.propose(mode,now)
            if plan is None:
                now+=31;plan=planner.propose(mode,now)
            plans.append(plan)
            planner.delivered(plan,f'Ideia simulada nova {index}.',now)
            planner.force_transition('vida_adulta')
            now+=31
        self.assertEqual({plan.topic for plan in plans},{'tema_personalizado'})
        self.assertTrue(all(plan.operator_topic=='Cultura pop e jogos' for plan in plans))
        self.assertGreaterEqual(len({plan.subtopic for plan in plans}),6)
        self.assertTrue(any('mantendo o tema personalizado' in plan.planning_reason for plan in plans))
        self.assertIn('tema ativo obrigatório',build_system_prompt({},True))
        planner.audience_reply_delivered()
        resumed=planner.propose(mode,now)
        self.assertEqual(resumed.topic,'tema_personalizado')
        self.assertEqual(resumed.intent,'resume')
        self.assertEqual(resumed.planning_reason,'retomada do tema após comentário')
        planner.delivered(resumed,'Comentário respondido.',now)
        planner.suggest_topic('Games retrô')
        changed=planner.propose(mode,now+1)
        self.assertEqual(changed.topic,'tema_personalizado')
        self.assertEqual(changed.operator_topic,'Games retrô')

    def test_autonomous_script_is_directed_to_real_viewers_without_repeating_cta(self):
        prompt=build_system_prompt({},True)
        self.assertIn('conversa com quem está acompanhando',prompt)
        self.assertIn('em algumas falas, não em todas',prompt)
        self.assertIn('não repita "galera" como bordão',prompt)
        self.assertIn('Só use nomes, contagens ou participação quando esses dados estiverem explicitamente disponíveis',prompt)

    def test_applied_theme_reaches_engine_snapshot_and_generator_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=AutonomousEngine(store_path=Path(directory)/'learning.json')
            self.addCleanup(engine.close)
            accepted=engine.configure_planning('Cultura pop brasileira',30)
            self.assertTrue(accepted['accepted'])
            self.assertEqual(engine.snapshot()['operator_topic'],'Cultura pop brasileira')
            plan=engine.planner.propose(load_config()['modes'][engine.mode],100.)
            self.assertEqual(plan.topic,'tema_personalizado')
            self.assertEqual(plan.operator_topic,'Cultura pop brasileira')

    def test_comments_within_three_seconds_are_not_throttled_and_bursts_survive_busy_pace(self):
        clock=Clock();flow=LiveFlowEngine(clock=clock)
        for index in range(40):flow.recent.append((clock(),f'viewer-{index}','CHAT_MESSAGE'))
        first=flow.decide(event('CHAT_MESSAGE','c1',author='one',text='fala sobre música'))
        second=flow.decide(event('CHAT_MESSAGE','c2',author='two',text='me conta dos games'))
        self.assertNotEqual(first.action,'IGNORE')
        self.assertNotEqual(second.action,'IGNORE')

    def test_relevant_questions_are_prioritized_over_semantic_trend_suppression(self):
        clock=Clock();flow=LiveFlowEngine(clock=clock);audience=LiveAudienceManager(clock=clock)
        results=[]
        for index in range(3):
            incoming=event('CHAT_MESSAGE',f'question-{index}',author=f'viewer-{index}',
                           text='Como a inteligência artificial pode ajudar uma empresa?')
            decision=flow.decide(incoming)
            self.assertIn(decision.action,{'ANSWER','DEEP_ANSWER','CONTINUE_THREAD'})
            result,item=audience.admit(incoming.event_id,incoming.author_id,incoming.text,
                priority=flow_priority(decision),flow_decision=decision)
            results.append((result,item))
        self.assertEqual([result for result,_ in results],['SELECT','SELECT','SELECT'])
        self.assertTrue(all(item.priority==3 for _,item in results))
        self.assertEqual(audience.counters['AUDIENCE_GROUPED_QUESTIONS'],0)

    def test_join_counters_separate_grouping_enqueue_and_confirmed_speech(self):
        clock=Clock();flow=LiveFlowEngine(clock=clock)
        flow.decide(event('VIEWER_JOIN','join-a',author='user-a',name='Lia'))
        flow.decide(event('VIEWER_JOIN','join-b',author='user-b',name='Bia'))
        clock.advance(3)
        ready=flow.flush()
        self.assertEqual(len(ready),1)
        self.assertEqual(ready[0].source_kind,'VIEWER_JOIN')
        self.assertEqual(len(ready[0].event_ids),2)
        flow.register_join_greeting('flow-join:batch-a',2)
        flow.finish_join_greeting('flow-join:batch-a',True)
        snapshot=flow.snapshot()
        self.assertEqual(snapshot['JOIN_EVENTS_RECEIVED'],2)
        self.assertEqual(snapshot['JOIN_EVENTS_GROUPED'],2)
        self.assertEqual(snapshot['JOIN_GREETINGS_READY'],2)
        self.assertEqual(snapshot['JOIN_GREETINGS_QUEUED'],2)
        self.assertEqual(snapshot['JOIN_EVENTS_GREETED'],2)
        self.assertEqual(snapshot['JOIN_GREETING_FAILURES'],0)

    def test_questions_and_gifts_outprioritize_grouped_join_greetings(self):
        director=LiveDirectorManager(lambda _unit:None)
        question=DirectorUnit('question','AUDIENCE','viewer',classification='QUESTION',
            metadata={'social_value':45})
        join=DirectorUnit('join','RULE','public-batch',event_type='FLOW_BATCH',
            classification='QUESTION',metadata={'social_value':50})
        gift=DirectorUnit('gift','HIGH_EVENT','viewer',event_type='GIFT_EVENT')
        self.assertGreater(director._priority(question),director._priority(join))
        self.assertGreater(director._priority(gift),director._priority(question))

    def test_same_comment_cooldown_is_short_and_event_id_dedup_remains(self):
        clock=Clock();flow=LiveFlowEngine(clock=clock)
        first=flow.decide(event('CHAT_MESSAGE','same-1',text='como funciona?'),presenter_answer=True)
        duplicate=flow.decide(event('CHAT_MESSAGE','same-2',text='como funciona?'),presenter_answer=True)
        self.assertEqual(first.action,'ANSWER')
        self.assertEqual(duplicate.action,'IGNORE')
        clock.advance(9)
        later=flow.decide(event('CHAT_MESSAGE','same-3',text='como funciona?'),presenter_answer=True)
        self.assertNotEqual(later.action,'IGNORE')
        repeated_id=flow.decide(event('CHAT_MESSAGE','same-3',text='outra pergunta'),presenter_answer=True)
        self.assertEqual(repeated_id.action,'IGNORE')

    def test_join_batches_once_even_when_busy_and_absence_creates_no_greeting(self):
        clock=Clock();flow=LiveFlowEngine(clock=clock)
        for index in range(45):flow.recent.append((clock(),f'viewer-{index}','CHAT_MESSAGE'))
        first=flow.decide(event('VIEWER_JOIN','join-1',author='new-user',name='Lia'))
        repeat=flow.decide(event('VIEWER_JOIN','join-2',author='new-user',name='Lia'))
        self.assertEqual(first.action,'BATCH')
        self.assertEqual(repeat.action,'IGNORE')
        clock.advance(3)
        greeting=flow.flush()
        self.assertEqual(len(greeting),1)
        self.assertIn('Lia',greeting[0].reply)
        empty=LiveFlowEngine(clock=clock)
        self.assertEqual(empty.flush(),[])

    def test_diagnostic_lines_show_comment_join_queue_and_model_state(self):
        lines=_zuko_metric_lines({'ZUKO_TIKTOK_CONNECTION':'CONNECTED',
            'ZUKO_TIKTOK_JOIN_CAPABILITY':'VERIFIED_REAL','ZUKO_TIKTOK_REAL_COMMENTS_RECEIVED':9,
            'ZUKO_TIKTOK_REAL_JOINS_RECEIVED':3,'ZUKO_JOIN_EVENTS_GROUPED':2,
            'ZUKO_JOIN_GREETINGS_QUEUED':2,'ZUKO_JOIN_EVENTS_GREETED':2,
            'ZUKO_GEMINI_CONFIGURED_MODEL':'gemini-3.8-flash',
            'ZUKO_GEMINI_ACTIVE_MODEL':'gemini-3.8-flash','ZUKO_AUTONOMY_STATE':'FALANDO',
            'ZUKO_DIRECTOR_QUEUE_DEPTH':1,'ZUKO_TTS_QUEUE_DEPTH':0,'ZUKO_TTS_STATE':'PLAYING'}, {})
        self.assertTrue(any('comentários 9' in line and 'JOINs 3' in line for line in lines))
        self.assertTrue(any('2 agrupados' in line and '2 saudados' in line for line in lines))
        self.assertTrue(any('gemini-3.8-flash' in line for line in lines))
        self.assertTrue(any('Director 1 aguardando' in line and 'TTS PLAYING' in line for line in lines))

    def test_dashboard_distinguishes_join_support_from_real_receipt(self):
        class Source:
            simulation=False
            def __init__(self,status):self.status=status
            def health(self):return {'connection':'CONNECTED','broadcaster':'@canal',
                'capability_validation':{'joins':self.status}}
        class Monitor:
            def __init__(self,status):self.tiktok_source=Source(status)
        supported=LiveDashboardV2.tiktok_connection_text(Monitor('SUPPORTED_UNVERIFIED'))
        received=LiveDashboardV2.tiktok_connection_text(Monitor('VERIFIED_REAL'))
        unavailable=LiveDashboardV2.tiktok_connection_text(Monitor('UNAVAILABLE'))
        self.assertIn('JOIN suportado',supported)
        self.assertIn('JOIN recebido nesta sessão',received)
        self.assertIn('JOIN indisponível',unavailable)

    def test_audience_ttl_and_malformed_provider_envelope_salvage_are_bounded(self):
        self.assertEqual(DirectorConfig().ttls['AUDIENCE'],45)
        self.assertEqual(DirectorConfig().ttls['CHAT'],45)
        self.assertEqual(DirectorConfig().ttls['QUESTION'],45)
        self.assertEqual(salvage_audience_speech('{"speech":"Resposta útil.","intent":'), 'Resposta útil.')
        self.assertIsNone(salvage_audience_speech('{"speech":"texto truncado'))
        self.assertEqual(salvage_audience_speech('{"speech":"ok","command":"run"}'),'ok')

    def test_shuffle_and_legacy_settings_are_backward_compatible(self):
        legacy={key:value for key,value in DEFAULT.items() if key!='shuffle'}
        self.assertFalse(validate_preferences(legacy)['shuffle'])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=root/'first.wav';second=root/'second.mp3'
            first.write_bytes(b'fake');second.write_bytes(b'fake')
            controller=SoundtrackController(root/'settings.json',threaded=False,
                backend_factory=lambda:None,rng=FirstChoice())
            self.addCleanup(controller.close)
            controller.add_files([first,second],licensed=True)
            controller.start(0)
            controller.set_shuffle(True)
            self.assertTrue(controller.next_track())
            self.assertEqual(controller.snapshot()['selected'],1)
            self.assertTrue(controller.next_track())
            self.assertEqual(controller.snapshot()['selected'],0)
            self.assertTrue(controller.snapshot()['preferences']['shuffle'])

    def test_shuffle_auto_advance_never_repeats_the_current_track(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);tracks=[root/'one.wav',root/'two.mp3',root/'three.wav']
            for track in tracks:track.write_bytes(b'fake')
            backend=FakeMusicBackend();clock=Clock();controller=SoundtrackController(root/'settings.json',
                backend_factory=lambda:backend,clock=clock,threaded=False,rng=FirstChoice())
            self.addCleanup(controller.close)
            controller.add_files(tracks,licensed=True);controller.set_shuffle(True);controller.start(0)
            controller.step();self.assertEqual(controller.snapshot()['current'],'one.wav')
            backend.state='stopped';clock.advance(.1);controller.step()
            self.assertEqual(controller.snapshot()['current'],'two.mp3')
            backend.state='stopped';clock.advance(.1);controller.step()
            self.assertEqual(controller.snapshot()['current'],'one.wav')


if __name__=='__main__': unittest.main()
