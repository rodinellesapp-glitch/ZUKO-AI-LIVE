"""V4 scenarios use the existing Presenter/Director/bridge and fake providers."""
from collections import OrderedDict, defaultdict
import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tkinter as tk

import test_zuko_ai_only as legacy
import test_zuko_v2_dashboard_animation as bridge_fixtures
import zuko_voice_config
from live_dashboard_v2 import LiveDashboardV2
from live_director import LiveDirectorManager, DirectorUnit
from live_response import LiveResponse
from movement_automation import MovementSelector
from zuko_presenter import ZukoAI, _same_semantic_idea
from zuko_v3_content import ContentPlan, ContentPlanner, load_config
from zuko_v3_engine import AutonomousEngine
from tts_manager import TTSManager, Utterance


class Clock:
    def __init__(self):self.now=0.
    def __call__(self):return self.now
    def advance(self,seconds):self.now+=seconds


class V4Tests(unittest.TestCase):
    def engine(self):
        clock=Clock();engine=AutonomousEngine(clock=clock)
        self.addCleanup(engine.close)
        return clock,engine

    def request(self,engine,**options):
        return engine.request(**{'tts_idle':True,'director_busy':False,'npc_ready':True,**options})

    def presenter(self,*,real=False,error=None):
        clock,engine=self.engine()
        p=legacy.ZukoAIOnlyTests().make_presenter(ai=legacy.FakeAI(error=error),real=real)
        p.ai.format_text=ZukoAI.format_text
        p.autonomy=engine;p.auto=True;engine.enable(True)
        p.monitor.voice.snapshot=lambda:{'TTS_STATE':'IDLE','TTS_QUEUE_DEPTH':0}
        p.monitor.director=LiveDirectorManager(p.dispatch,tts_snapshot=p.monitor.voice.snapshot)
        return p,clock,engine

    def auto_unit(self,p,engine):
        ident,plan=self.request(engine)
        content=LiveResponse(ident,'','','ZUKO_AI_PENDING',0,time.monotonic(),'ZUKO',True)
        return DirectorUnit(ident,'PRESENTER','',content_ref=content,
            metadata={'zuko_auto':True,'v3_plan':plan.context(),'correlation_id':ident})

    def bridge(self):
        bridge=bridge_fixtures.bridge_for_status()
        bridge.auto_selector=MovementSelector(clock=lambda:10)
        bridge.seen=OrderedDict();bridge.auto_commands=[]
        bridge.walking_requested=False;bridge.manual_current=None
        return bridge

    def test_all_eight_controller_states_in_one_existing_engine(self):
        clock,e=self.engine();seen={e.controller_state}
        e.enable(True);seen.add(e.controller_state)
        ident,plan=self.request(e);e.speech_started(ident);seen.add(e.controller_state)
        e.completed(ident,'Uma abertura simulada.');seen.add(e.controller_state)
        clock.advance(26);ident,plan=self.request(e);seen.add(e.controller_state)
        e.completed(ident,'Desenvolvimento do tema.')
        e.track_audience('a','CHAT_MESSAGE');seen.add(e.controller_state)
        e.audience_delivered('a');e.track_audience('b','GIFT');seen.add(e.controller_state)
        e.audience_delivered('b');clock.advance(26)
        ident,plan=self.request(e);seen.add(e.controller_state)
        self.assertEqual(plan.intent,'resume')
        e.pause(True);seen.add(e.controller_state)
        self.assertEqual(seen,e.PHASES)

    def test_one_hour_silent_show_is_bounded_and_no_speculative_batch(self):
        clock,e=self.engine();e.enable(True);e.configure_planning('histórias de supermercado',20)
        maximum=0
        while clock.now<3600:
            proposal=self.request(e)
            if proposal:
                ident,plan=proposal;maximum=max(maximum,len(e.pending))
                self.assertEqual(plan.operator_topic,'histórias de supermercado')
                e.speech_started(ident);clock.advance(3)
                e.completed(ident,f'Fala simulada número {e.sequence}.')
            clock.advance(1)
        self.assertEqual(maximum,1)
        self.assertGreater(e.snapshot()['completed'],70)
        self.assertEqual(e.snapshot()['gemini_calls'],0)
        self.assertLessEqual(len(e.planner.resume_points),4)
        self.assertLessEqual(e.memory.sizes()['turns'],24)

    def test_comment_during_monologue_queues_before_next_auto_and_resumes_topic(self):
        p,clock,e=self.presenter();unit=self.auto_unit(p,e)
        self.assertTrue(p.monitor.director.submit(unit));p.monitor.director.run_once()
        auto=p.monitor.queued[0];p.tts_result('TTS_INICIO',auto)
        topic=e.planner.topic or e.pending[unit.unit_id]['plan'].topic
        p.last_comment=0
        event=SimpleNamespace(event_type='CHAT_MESSAGE',author_name='Ana',author_key='ana',
            text='Hoje o mercado estava cheio.',gift_type='',source='TIKTOK_SIMULATOR')
        p.remember('comment-1',event);p.ai.text='Foi uma aventura para conseguir passar pelo corredor!'
        comment=DirectorUnit('comment-1','AUDIENCE','ana',content_ref=SimpleNamespace(author='Ana',text=event.text))
        p.monitor.director.submit(comment);p.selected(comment);p.monitor.director.run_once()
        self.assertEqual(len(p.monitor.queued),2)
        self.assertIsNone(self.request(e))
        self.assertEqual(e.snapshot()['audience_waiting'],1)
        p.tts_result('TTS_OK',auto)
        reply=p.monitor.queued[1];p.tts_result('TTS_INICIO',reply);p.tts_result('TTS_OK',reply)
        self.assertEqual(e.snapshot()['audience_waiting'],0)
        clock.advance(26);_,resume=self.request(e)
        self.assertEqual((resume.intent,resume.topic),('resume',topic))

    def test_many_likes_do_not_become_pending_replies_or_verified_gifts(self):
        _,e=self.engine();e.enable(True)
        for index in range(4000):e.observe_signal('LIKE','sim-'+str(index),real=False)
        state=e.snapshot()
        self.assertEqual(state['audience_waiting'],0)
        self.assertEqual(state['pending'],0)
        self.assertEqual(state['gemini_calls'],0)
        self.assertEqual(state['real_gifts'],'NOT_VERIFIED')
        self.assertEqual(state['real_followers'],'NOT_VERIFIED')
        self.assertLessEqual(e.memory.sizes()['identities'],1200)

    def test_gift_during_response_does_not_replace_current_speech(self):
        _,e=self.engine();e.enable(True)
        e.track_audience('chat','CHAT_MESSAGE');e.speech_started('chat')
        e.observe_signal('GIFT','gift',real=False);e.track_audience('gift','GIFT')
        self.assertEqual(e.controller_state,'RESPONDING')
        self.assertEqual(e.snapshot()['audience_events_waiting'],1)
        self.assertIsNone(self.request(e))
        e.audience_delivered('chat');e.speech_started('gift')
        self.assertEqual(e.controller_state,'REACTING')
        e.audience_delivered('gift')
        self.assertEqual(e.snapshot()['audience_events_waiting'],0)
        self.assertEqual(e.snapshot()['real_gifts'],'NOT_VERIFIED')

    def test_follower_mock_generates_once_and_real_status_remains_unverified(self):
        p,_,e=self.presenter()
        event=SimpleNamespace(event_type='FOLLOW',author_name='Rafa',author_key='rafa',
            text='',gift_type='',source='TIKTOK_SIMULATOR')
        p.remember('follow-1',event)
        unit=DirectorUnit('follow-1','HIGH_EVENT','rafa',event_type='FOLLOW',content_ref=SimpleNamespace())
        self.assertTrue(p.monitor.director.submit(unit));p.selected(unit)
        p.monitor.director.run_once()
        self.assertEqual(len(p.monitor.queued),1)
        self.assertEqual(p.litellm.calls,0)
        self.assertFalse(p.monitor.director.submit(unit))
        self.assertEqual(e.snapshot()['real_followers'],'NOT_VERIFIED')

    def test_failed_gemini_uses_existing_local_fallback_and_shared_grant(self):
        p,_,e=self.presenter(real=True);e.config['limits']['audience_reserve_calls']=0
        p.ollama_enabled=True
        p.gemini_budget.authorize(4,0);p.litellm.error=RuntimeError('service unavailable')
        unit=self.auto_unit(p,e)
        p.monitor.director.submit(unit);p.monitor.director.run_once()
        self.assertEqual(len(p.monitor.queued),1)
        self.assertEqual(p.monitor.queued[0].provider,'ZUKO_OLLAMA_LOCAL')
        self.assertEqual(p.gemini_budget.snapshot(0)['used'],1)

    def test_autonomy_truncation_fails_without_speaking_partial_gemini_text(self):
        p,_,e=self.presenter(real=True)
        e.config['limits']['audience_reserve_calls']=0
        p.ollama_enabled=False
        p.gemini_budget.authorize(4,0)
        meta={'model':'gemini-3.8-flash','finish_reason':'length',
            'native_finish_reason':'MAX_TOKENS','prompt_tokens':124,
            'completion_tokens':512,'total_tokens':636,'reasoning_tokens':252,'elapsed_ms':8000.0}
        p.litellm=legacy.FakeLiteLLM(error=legacy.ProviderDiagnosticError(
            'GEMINI_OUTPUT_TRUNCATED','TRUNCATED','provider_response',response_metadata=meta))
        unit=self.auto_unit(p,e)
        p.monitor.director.submit(unit);p.monitor.director.run_once()
        self.assertEqual(p.monitor.queued,[])
        self.assertEqual(unit.metadata.get('zuko_gemini_response',{}).get('finish_reason'),'length',
                         (unit.metadata,p.history))
        self.assertTrue(any(row.get('event')=='AI_GENERATION_TRUNCATED' for row in p.history))
        self.assertEqual(e.snapshot()['failures'],1)

    def test_ollama_unavailable_silences_once_then_backs_off_without_loop(self):
        p,clock,e=self.presenter(error='Ollama unavailable')
        p.ollama_enabled=True
        unit=self.auto_unit(p,e);p.monitor.director.submit(unit);p.monitor.director.run_once()
        self.assertEqual(p.monitor.queued,[])
        self.assertEqual(e.snapshot()['failures'],1)
        for _ in range(20):self.assertIsNone(self.request(e))
        self.assertEqual(len(p.ai.events),1)
        self.assertEqual(p.litellm.calls,0)
        clock.advance(16);self.assertIsNotNone(self.request(e))

    def test_tts_busy_and_manual_activity_never_generate_auto(self):
        _,e=self.engine();e.enable(True)
        for values in ({'tts_idle':False},{'godot_speaking':True},{'director_busy':True},{'manual_active':True}):
            for _ in range(20):self.assertIsNone(self.request(e,**values))
        self.assertEqual(e.sequence,0)

    def test_manual_interruption_cancels_inflight_auto_before_tts(self):
        p,_,e=self.presenter();unit=self.auto_unit(p,e)
        def manual_arrives(event):
            p.monitor.npc.manual_override=True
            return 'Uma resposta atrasada que não deve tocar.','OLLAMA_LOCAL'
        p.ai.response=manual_arrives
        p.monitor.director.submit(unit);p.monitor.director.run_once()
        self.assertEqual(p.monitor.queued,[])
        self.assertEqual(e.snapshot()['pending'],0)

    def test_dashboard_constructs_six_tabs_and_v4_controls_with_runtime_detached(self):
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        controls=defaultdict(lambda:lambda *args,**kwargs:True)
        with patch.object(LiveDashboardV2,'_tick',lambda self:None),\
             patch('live_dashboard_v2.ZigViewerButton',Mock()),\
             patch('zuko_voice_config.configure_limit',Mock()):
            dashboard=LiveDashboardV2(root,controls,SimpleNamespace(),source='tiktok-sim')
            root.update_idletasks()
        self.assertEqual(len(dashboard.notebook.tabs()),6)
        self.assertFalse(dashboard.v3_enabled.get())
        self.assertEqual(dashboard.v4_interval.get(),25)
        self.assertEqual(dashboard.v4_topic.get(),'')
        self.assertIn('Comentários aguardando',dashboard.v4_pending_status.cget('text'))

    def test_pause_resume_drops_pending_and_spends_no_model_calls(self):
        clock,e=self.engine();e.enable(True);self.request(e)
        e.pause(True)
        self.assertEqual(e.controller_state,'PAUSED')
        self.assertEqual(e.pending,{})
        self.assertFalse(e.allow_gemini({'authorized':True,'remaining':50})[0])
        clock.advance(500);self.assertIsNone(self.request(e))
        e.pause(False);self.assertIsNone(self.request(e))
        clock.advance(26);self.assertIsNotNone(self.request(e))
        self.assertEqual(e.snapshot()['gemini_calls'],0)

    def test_session_limit_preserves_audience_budget_and_local_route(self):
        p,_,e=self.presenter(real=True);p.gemini_budget.authorize(5,0)
        p.ollama_enabled=True
        e.counts['gemini_calls']=e.config['limits']['autonomous_gemini_per_session']
        unit=self.auto_unit(p,e);p.monitor.director.submit(unit);p.monitor.director.run_once()
        self.assertEqual(p.litellm.calls,0)
        self.assertEqual(p.gemini_budget.snapshot(0)['used'],0)
        self.assertEqual(p.monitor.queued[0].provider,'ZUKO_OLLAMA_LOCAL')

    def test_duplicate_selected_message_and_dropped_message_do_not_stick(self):
        clock,e=self.engine();e.enable(True)
        self.assertTrue(e.track_audience('id','CHAT_MESSAGE'))
        self.assertFalse(e.track_audience('id','CHAT_MESSAGE'))
        self.assertEqual(e.snapshot()['audience_waiting'],1)
        clock.advance(2);e.reconcile(set())
        self.assertEqual(e.snapshot()['audience_waiting'],0)
        clock.advance(26);self.assertIsNotNone(self.request(e))

    def test_multiple_viewers_use_existing_separate_recent_context(self):
        p,_,e=self.presenter()
        for author,text in (('Ana','Meu dia no trabalho foi pesado.'),('Bruno','Meu ônibus atrasou.')):
            event=SimpleNamespace(author_name=author,author_key=author,event_type='CHAT_MESSAGE',text=text)
            p.conversation.delivered(event,'Fala entregue para '+author+'.')
        ana=SimpleNamespace(author_name='Ana',author_key='Ana',event_type='CHAT_MESSAGE',text='E como assim?')
        unit=DirectorUnit('ana-cont','AUDIENCE','Ana',ttl=10,metadata={'epoch':0})
        p._response_bounded(ana,unit,0)
        context=p.ai.events[-1].recent_context
        self.assertEqual(len(context),1);self.assertIn('trabalho',context[0]['comment'])
        self.assertNotIn('ônibus',json.dumps(context,ensure_ascii=False))

    def test_questions_stories_and_resume_anchors_are_bounded_and_supplied(self):
        planner=ContentPlanner()
        for index in range(30):
            plan=ContentPlan('HISTÓRIAS DO COTIDIANO','vida_adulta','APRESENTANDO','story','joy','Uma situação imaginada.')
            planner.delivered(plan,f'Situação imaginada {index}. Como foi seu dia número {index}?',index)
        self.assertEqual(len(planner.questions),8);self.assertEqual(len(planner.stories),3)
        self.assertEqual(len(planner.resume_points),4)
        self.assertTrue(planner.repeated_question('Como foi seu dia número 29?'))
        current=planner.propose(load_config()['modes']['NORMAL'],40)
        self.assertEqual(len(current.asked_questions),4)
        self.assertTrue(current.subtopic);self.assertTrue(current.next_idea)

    def test_repeated_autonomous_question_is_suppressed_before_queue(self):
        p,_,e=self.presenter();unit=self.auto_unit(p,e)
        e.planner.questions.append('Como foi seu dia?');p.ai.text='Como foi seu dia?'
        p.monitor.director.submit(unit);p.monitor.director.run_once()
        self.assertEqual(p.monitor.queued,[])
        self.assertEqual(unit.metadata['zuko_outcome_reason'],'REPEAT_GUARD')
        self.assertEqual(e.snapshot()['failures'],1)

    def test_semantic_repeat_only_suppresses_auto_and_requests_topic_transition(self):
        p,_,engine=self.presenter()
        previous='Quem nunca chegou no mercado com uma lista curta e saiu com a sacola cheia?'
        candidate='A gente entra no supermercado pensando em pegar o básico, mas sai com o carrinho cheio e a lista esquecida.'
        self.assertTrue(_same_semantic_idea(previous,candidate))
        p.conversation.delivered(SimpleNamespace(event_type='PRESENTER_AUTONOMOUS',author_key='__zuko_live__',text=''),previous)
        auto=self.auto_unit(p,engine)
        viewer=DirectorUnit('viewer-1','TIKTOK','',metadata={'correlation_id':'viewer-1'})
        self.assertTrue(p._repeat_guard(candidate,auto))
        self.assertFalse(p._repeat_guard(candidate,viewer))
        prior_topic=auto.metadata['v3_plan']['topic']
        p.ai.text=candidate
        p.monitor.director.submit(auto);p.monitor.director.run_once()
        self.assertEqual(p.monitor.queued,[])
        self.assertTrue(engine.planner.forced_transition)
        next_plan=engine.planner.propose(load_config()['modes']['NORMAL'],time.monotonic())
        self.assertNotEqual(next_plan.topic,prior_topic)

    def test_comment_receive_counter_is_unique_and_separate_from_spoken(self):
        p,_,_=self.presenter()
        comment=SimpleNamespace(comment_id='comment-1',author='viewer',text='E esse assunto?',source='TIKTOK',received_at=time.monotonic())
        p.observe_comment(comment);p.observe_comment(comment)
        stats=p.snapshot()
        self.assertEqual(stats['ZUKO_COMMENTS_RECEIVED'],1)
        self.assertEqual(stats['ZUKO_COMMENT_RESPONSES_ENQUEUED'],0)
        self.assertEqual(stats['ZUKO_COMMENT_RESPONSES_SPOKEN'],0)

    def test_godot_speaking_gesture_confirms_bridge_and_synthesis_blocks_idle(self):
        bridge=self.bridge()
        bridge._queue_movement_confirmation('speech-1','SPEECH','Wave')
        bridge._observe_presentation_status({'animation':'Wave','speaking':True,'reacting':True,'walking':False})
        self.assertFalse(any(item['correlation_id']=='speech-1' for item in bridge.pending_movements))
        self.assertTrue(any(row[0]=='SPEECH_ANIMATION_CONFIRMED' for row in bridge.records))
        bridge.tts('TTS_STATE',None,'SYNTHESIZING')
        self.assertTrue(bridge.tts_busy)
        bridge.tts('TTS_STATE',None,'IDLE')
        self.assertFalse(bridge.tts_busy)

    def test_tts_cancellation_keeps_explicit_reason_without_extra_player(self):
        events=[]
        manager=TTSManager(lambda *_:None,lambda *_:None,lambda *args:events.append(args))
        item=Utterance(SimpleNamespace(comment_id='voice-1'),'',0,time.monotonic(),1,'ZUKO',threading.Event())
        manager.current=item
        with patch('tts_manager.pygame.mixer.get_init',return_value=False):
            manager.cancel_current(reason='OPERATOR_STOP')
        self.assertTrue(item.cancelled.is_set())
        self.assertEqual(item.cancel_reason,'OPERATOR_STOP')
        self.assertIn('TTS_STATE', [event[0] for event in events])

    def test_voice_fallback_counts_keep_bounded_reason_categories(self):
        with patch.object(zuko_voice_config,'_fallback_count',0), \
             patch.object(zuko_voice_config,'_last_fallback',''), \
             patch.object(zuko_voice_config,'_fallback_reasons',defaultdict(int)):
            zuko_voice_config.record_fallback('Gemini timeout')
            zuko_voice_config.record_fallback('uso não autorizado ou limite esgotado')
            reasons=zuko_voice_config.authorization_status()['fallback_reasons']
        self.assertEqual(reasons,{'TIMEOUT':1,'AUTHORIZATION_OR_LIMIT':1})

    def test_ollama_failure_opens_bounded_circuit_without_second_request(self):
        p,_,_=self.presenter()
        calls=[]
        p.ai.response=Mock(side_effect=lambda _event: (calls.append(1), (_ for _ in ()).throw(RuntimeError('offline')))[1])
        unit=SimpleNamespace(unit_id='local-fail',source='LOCAL',conversation_version=0,metadata={'correlation_id':'local-fail','epoch':p.monitor.director.epoch},ttl=30,created_at=time.monotonic())
        event=SimpleNamespace(event_type='CHAT_MESSAGE',provider_cancelled=lambda:False,provider_deadline=None)
        text,provider,_=p._run_local_generation(event,unit,0,'GEMINI_COOLDOWN')
        self.assertIsNone(text);self.assertEqual(provider,'AI_UNAVAILABLE');self.assertEqual(len(calls),1)
        text,provider,_=p._run_local_generation(event,unit,0,'GEMINI_COOLDOWN')
        self.assertIsNone(text);self.assertEqual(provider,'AI_UNAVAILABLE');self.assertEqual(len(calls),1)

    def test_operator_plan_applies_next_without_mutating_active_or_authorization(self):
        _,e=self.engine();e.enable(True);ident,original=self.request(e)
        applied=e.configure_planning('grupo de WhatsApp da família',40)
        self.assertEqual(applied,{'accepted':True,'operator_topic':'grupo de WhatsApp da família',
                                  'interval_seconds':40})
        self.assertEqual(e.pending[ident]['plan'],original)
        e.completed(ident,'Uma fala já em andamento.')
        e.clock.advance(41);_,next_plan=self.request(e)
        self.assertEqual(next_plan.operator_topic,'grupo de WhatsApp da família')
        self.assertEqual(next_plan.intent,'transition')
        self.assertEqual(e.snapshot()['interval_seconds'],40)
        for invalid in (0,301,True):
            with self.assertRaises(ValueError):e.configure_planning('teste',invalid)

    def test_bounded_provider_context_keeps_plan_and_never_cuts_json(self):
        _,engine=self.engine();engine.enable(True)
        _,plan=self.request(engine)
        event=SimpleNamespace(generation_context={'v3_plan':plan.context(),
            'source_status':'SIMULATION','programme_context':{'public_programme_speech':['x'*10000]*20},
            'session_recap':{'unneeded':'x'*10000}},
            recent_speech=[{'comment':'x'*1000,'spoken_reply':'y'*1000}]*50)
        text=ZukoAI.programme_context(event,'vida_adulta',{'topics':['vida_adulta'],'events':['x'*1000]*50})
        self.assertLessEqual(len(text),3500)
        data=json.loads(text)
        self.assertEqual(data['event_context']['v3_plan']['topic'],plan.topic)
        self.assertLessEqual(len(data['recent_public_speech']),3)
        self.assertNotIn('programme_context',data['event_context'])

    def test_dashboard_callbacks_use_existing_engine_and_do_not_grant_gemini(self):
        p,_,e=self.presenter();d=LiveDashboardV2.__new__(LiveDashboardV2)
        d.monitor=lambda:p.monitor;p.monitor.zuko=p
        d.v4_topic=SimpleNamespace(get=lambda:'ônibus e trânsito',set=Mock())
        d.v4_interval=SimpleNamespace(get=lambda:35,set=Mock())
        d._refresh_autonomy_status=Mock();d._refresh_v4_plan_status=Mock();d.v3_status=Mock()
        self.assertTrue(d.apply_autonomy_plan())
        self.assertEqual(e.snapshot()['operator_topic'],'ônibus e trânsito')
        self.assertFalse(p.gemini_budget.snapshot(0)['authorized'])

    def test_dashboard_confirms_controller_values_and_marks_unapplied_edits(self):
        _,engine=self.engine()
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        controls=defaultdict(lambda:lambda *args,**kwargs:True)
        with patch.object(LiveDashboardV2,'_tick',lambda self:None),\
             patch('live_dashboard_v2.ZigViewerButton',Mock()),\
             patch('zuko_voice_config.configure_limit',Mock()):
            dashboard=LiveDashboardV2(root,controls,SimpleNamespace(),source='tiktok-sim')
            root.update_idletasks()
        dashboard.runtime_monitor=SimpleNamespace(zuko=SimpleNamespace(autonomy=engine))
        dashboard._refresh_autonomy_status=Mock()
        dashboard.v4_topic.set('ônibus e trânsito')
        dashboard.v4_interval.set(40)
        self.assertIn('STATUS: Alteração pendente',dashboard.v4_plan_status.cget('text'))
        self.assertTrue(dashboard.apply_autonomy_plan())
        active=dashboard.v4_plan_status.cget('text')
        self.assertIn('TEMA ATIVO: ônibus e trânsito',active)
        self.assertIn('INTERVALO ATIVO: 40 s',active)
        self.assertIn('STATUS: Aplicado com sucesso',active)
        self.assertNotIn('ÚLTIMA APLICAÇÃO: não disponível',active)
        dashboard.v4_topic.set('tema ainda não aplicado')
        self.assertIn('STATUS: Alteração pendente',dashboard.v4_plan_status.cget('text'))
        self.assertEqual(engine.snapshot()['operator_topic'],'ônibus e trânsito')
        dashboard.v4_interval.set(9)
        self.assertFalse(dashboard.apply_autonomy_plan())
        failed=dashboard.v4_plan_status.cget('text')
        self.assertIn('STATUS: Erro:',failed)
        self.assertIn('INTERVALO ATIVO: 40 s',failed)
        self.assertEqual(engine.snapshot()['interval_seconds'],40)

    def test_applied_theme_is_attached_to_the_next_generation_context(self):
        presenter,clock,engine=self.presenter()
        engine.configure_planning('ônibus e trânsito',40)
        clock.advance(16)
        unit=self.auto_unit(presenter,engine)
        self.assertEqual(unit.metadata['v3_plan']['operator_topic'],'ônibus e trânsito')
        self.assertTrue(presenter.monitor.director.submit(unit))
        presenter.monitor.director.run_once()
        self.assertEqual(len(presenter.ai.events),1)
        generation_event=presenter.ai.events[0]
        context=json.loads(ZukoAI.programme_context(generation_event,
            unit.metadata['v3_plan']['topic'],{}))
        self.assertEqual(context['event_context']['v3_plan']['operator_topic'],'ônibus e trânsito')
        self.assertEqual(engine.snapshot()['interval_seconds'],40)

    def test_manual_finished_status_releases_auto_without_dashboard_widget(self):
        b=self.bridge();self.assertFalse(hasattr(b,'walk_button'))
        self.assertTrue(b.manual_animation('Wave',False));b.manual_commands.get_nowait()
        b._observe_presentation_status({'animation':'Wave','manual':True,'paused':False,'reacting':True,'source':'MANUAL'})
        self.assertTrue(b.manual_override)
        b._observe_presentation_status({'animation':'Idle','manual':False,'paused':False,'reacting':False,'source':'GODOT'})
        self.assertFalse(b.manual_override)
        self.assertTrue(b.automatic_event('follow','FOLLOW'))
        self.assertTrue(any(name=='MANUAL_PRIORITY_RELEASED' for name,_ in b.records))

    def test_active_manual_walk_remains_priority_indefinitely(self):
        b=self.bridge();b.manual_animation('Walk',False);b.manual_commands.get_nowait()
        for _ in range(20):
            b._observe_presentation_status({'animation':'Walk','manual':True,'paused':False,'walking':True,'source':'MANUAL'})
        self.assertTrue(b.manual_override)
        self.assertFalse(b.automatic_event('gift','GIFT'))
        self.assertTrue(any(data.get('reason')=='manual_priority' for _,data in b.records))

    def test_stale_or_partial_status_does_not_release_new_manual_request(self):
        b=self.bridge();b.manual_animation('Yes',False);b.manual_commands.get_nowait()
        for status in ({'animation':'Idle','manual':False,'paused':False},{'animation':'Idle'}):
            b._observe_presentation_status(status)
            self.assertTrue(b.manual_override)

    def test_manual_pause_or_external_pause_is_never_implicitly_released(self):
        for attr in ('manual_paused','external_paused'):
            b=self.bridge();b.manual_override=True;b.manual_confirmed=True
            setattr(b,attr,True)
            b._observe_presentation_status({'animation':'Idle','manual':False,'paused':False})
            self.assertTrue(b.manual_override)

    def test_no_reflection_call_while_audience_waits_or_paused(self):
        _,e=self.engine();e.enable(True);e.counts['completed']=20
        e.track_audience('q','CHAT');model=Mock()
        self.assertFalse(e.maybe_reflect(idle=True,model=model))
        e.pause(True);self.assertFalse(e.maybe_reflect(idle=True,model=model))
        model.assert_not_called()


if __name__=='__main__':unittest.main()
