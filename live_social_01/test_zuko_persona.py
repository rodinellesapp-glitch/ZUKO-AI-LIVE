"""Offline persona contract and existing queue/gesture integration, without providers."""
import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import test_zuko_ai_only as legacy
from movement_automation import MovementSelector
from npc_panel_bridge import NPCPanelBridge
from zuko_presenter import ZukoAI
from zuko_v3_content import (ContentPlanner, EMOTION_ALIASES, build_system_prompt,
                             decode_generation, load_config)
from zuko_v3_memory import AdaptiveMemory


class PersonaTests(unittest.TestCase):
    def test_provider_prompt_uses_same_persona_with_distinct_output_contracts(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'zuko_personality.json').read_text(encoding='utf-8'))
        for structured in (False,True):
            prompt=build_system_prompt(config,True,structured=structured)
            self.assertIn('cotidiano do brasileiro',prompt)
            self.assertIn('source_status=SIMULATION',prompt)
            self.assertIn('não misturar histórias',prompt.lower().replace('sem misturar histórias','não misturar histórias'))
            self.assertEqual('Retorne JSON compacto' in prompt,structured)

    def test_streamer_identity_and_prompt_examples_cover_varied_conversation(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'zuko_personality.json').read_text(encoding='utf-8'))
        self.assertIn('streamer brasileiro',config['style'].lower())
        self.assertIn('entre amigos',config['style'].lower())
        self.assertIn('empatia',config['instruction'].lower())
        prompt=build_system_prompt(config,True,structured=True).lower()
        for phrase in ('converse como streamer brasileiro','nunca como telejornal',
                       'comentários reais parecidos continuam','deixe o humor de lado',
                       'deixe pausas naturais','comentários novos têm prioridade',
                       'não inclua instruções de animação'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,prompt)
        library=json.loads((Path(__file__).with_name('zuko_v3_prompt.json')).read_text(encoding='utf-8'))
        examples=' '.join(row['situation']+' '+row['speech'] for row in library['examples']).lower()
        self.assertIn('ônibus',examples)
        self.assertIn('empatia',examples)
        self.assertIn('retomada após interrupção',examples)
        self.assertNotIn('café',examples)
        self.assertLessEqual(examples.count('mercado'),1)

    def test_offline_multi_viewer_chat_keeps_repeats_silence_and_empathy_context(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'zuko_personality.json').read_text(encoding='utf-8'))
        ai=ZukoAI(config)
        transcript=[
            ('CHAT_MESSAGE','Ana','Meu ônibus atrasou e perdi o começo da reunião.',[],[]),
            ('CHAT_MESSAGE','Bruno','O meu também atrasou hoje.',
             [{'author':'Ana','comment':'Meu ônibus atrasou e perdi o começo da reunião.',
               'spoken_reply':'Você perdeu só o começo ou a reunião inteira?'}],
             [{'comment':'Meu ônibus atrasou e perdi o começo da reunião.',
               'spoken_reply':'Você perdeu só o começo ou a reunião inteira?'}]),
            ('CHAT_MESSAGE','Bruno','O meu também atrasou hoje.',
             [{'author':'Ana','comment':'Meu ônibus atrasou e perdi o começo da reunião.',
               'spoken_reply':'Você perdeu só o começo ou a reunião inteira?'}],[]),
            ('PRESENTER_AUTONOMOUS','','',[],[
             {'comment':'Meu ônibus atrasou e perdi o começo da reunião.',
              'spoken_reply':'Você perdeu só o começo ou a reunião inteira?'}]),
            ('CHAT_MESSAGE','Lia','Estou cuidando da minha mãe e estou muito cansada.',[],[]),
        ]
        requests=[]
        for index,(kind,author,comment,recent,public) in enumerate(transcript):
            event=SimpleNamespace(event_type=kind,author_name=author,text=comment,gift_type='',
                source='SIMULATION',generation_context={'source_status':'SIMULATION'},
                recent_context=recent,recent_speech=public)
            requests.append(ai._request_data(event))
        self.assertEqual([row['comment'] for row in requests[:3]],
                         [transcript[index][2] for index in range(3)])
        self.assertEqual(requests[1]['recent_context'][0]['author'],'Ana')
        self.assertEqual(requests[2]['comment'],requests[1]['comment'])
        self.assertEqual(requests[3]['event'],'PRESENTER_AUTONOMOUS')
        self.assertEqual(requests[3]['comment'],'')
        self.assertTrue(requests[3]['recent_public_speech'])
        self.assertIn('cansada',requests[4]['comment'])
        self.assertTrue(all(row['source_status']=='SIMULATION' for row in requests))
        self.assertIn('deixe o humor de lado',build_system_prompt(config,False,structured=True).lower())
        replies=[
            {'speech':'Você perdeu só o começo da reunião ou ganhou uma desculpa oficial para chegar depois?','emotion':'AMUSED','intent':'humor','animation':'Yes'},
            {'speech':'Dois ônibus atrasados no mesmo papo; hoje o transporte resolveu participar da reunião também.','emotion':'AMUSED','intent':'comment','animation':'Wave'},
            {'speech':'Entendi, aconteceu de novo. O que costuma salvar seu tempo enquanto você espera?','emotion':'CURIOUS','intent':'question','animation':'Idle'},
            {'speech':'Já demos bastante volta nesse atraso. Mudando de assunto: qual invenção pequena facilitou sua rotina?','emotion':'CURIOUS','intent':'transition','animation':'Idle'},
            {'speech':'Sinto muito que você esteja tão cansada. Se quiser contar mais, eu acompanho; não precisa transformar isso em piada.','emotion':'EMPATHETIC','intent':'support','animation':'Wave'},
        ]
        spoken=[]
        for reply in replies:
            speech,metadata=decode_generation(json.dumps(reply,ensure_ascii=False))
            spoken.append(ZukoAI.format_text(speech))
            self.assertEqual(speech,ZukoAI.format_text(speech))
            self.assertIn(metadata['emotion'],{'joy','calm','empathy','surprise','gratitude'})
            self.assertIn(metadata['animation'],{'Idle','Wave','Yes','No','Jump'})
        self.assertEqual(len(set(spoken)),len(spoken))
        self.assertEqual([decode_generation(json.dumps(reply))[1]['emotion'] for reply in replies],
                         ['joy','joy','calm','calm','empathy'])

    def test_all_eight_emotion_names_are_compatible_with_existing_gesture_hints(self):
        for supplied,canonical in EMOTION_ALIASES.items():
            with self.subTest(emotion=supplied):
                speech,metadata=decode_generation(json.dumps({'speech':'Uma fala do teste.',
                    'emotion':supplied.upper(),'intent':'comment','animation':'Idle',
                    'topic':'vida_adulta','reply_to':'local:msg-1'}))
                self.assertEqual(metadata['emotion'],canonical)
                self.assertEqual(speech,'Uma fala do teste.')

    def test_acting_cues_never_become_spoken_words(self):
        cases=('[Acena] Chega mais! [Ri] Hoje o assunto rendeu.',
               'Chega mais! [Faz uma pausa curta] Hoje o assunto rendeu.')
        for text in cases:
            speech,_=decode_generation(text)
            self.assertEqual(ZukoAI.format_text(speech),'Chega mais! Hoje o assunto rendeu.')
        speech,_=decode_generation(json.dumps({'speech':cases[0]}))
        self.assertNotIn('Acena',speech)
        with self.assertRaises(ValueError):decode_generation('[Acena]')

    def test_complete_three_sentence_response_is_not_limited_to_old_35_words(self):
        text=('Sair de casa para comprar uma coisa pode virar uma pequena aventura no mercado. '
              'A gente encontra uma promoção, esquece a lista e ainda volta pensando naquele produto que deixou na prateleira. '
              'O orçamento também precisava de um passeio?')
        self.assertGreater(len(text.split()),35)
        self.assertLessEqual(len(text.split()),55)
        self.assertEqual(ZukoAI.format_text(text),text)

    def test_executable_fields_and_unavailable_animation_are_rejected(self):
        for extra in ({'execute':'delete'},{'animation':'WalkWave'}, {'animation':['Wave']},
                      {'emotion':'ANGRY'}, {'reply_to':42}, {'topic':'private/file'}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                decode_generation(json.dumps({'speech':'Teste seguro.',**extra}))

    def test_local_structured_response_reaches_single_queue_with_hints(self):
        payload=json.dumps({'speech':'[Acena] Foi uma correria daquelas. Descansa um pouco!',
            'emotion':'EMPATHETIC','intent':'support','animation':'Wave',
            'topic':'trabalho_e_correria','reply_to':'msg-1'})
        p=legacy.ZukoAIOnlyTests().make_presenter(ai=legacy.FakeAI(payload))
        p.ai.format_text=ZukoAI.format_text
        p.monitor.npc.set_speech_hint=Mock()
        legacy.ZukoAIOnlyTests().add_comment(p,'msg-1','Mariana','Trabalhei demais hoje.')
        self.assertEqual(len(p.monitor.queued),1)
        self.assertEqual(p.monitor.queued[0].text,'Foi uma correria daquelas. Descansa um pouco!')
        p.monitor.npc.set_speech_hint.assert_called_once_with('msg-1','support','empathy',1)
        self.assertEqual(p.litellm.calls,0)
        self.assertFalse(p.gemini_budget.snapshot(0)['authorized'])
        self.assertEqual(p.ai.events[0].generation_context['source_status'],'SIMULATION')
        self.assertEqual(p.ai.events[0].generation_context['reply_to'],'msg-1')

    def test_gemini_mock_uses_structured_contract_and_discards_metadata_from_tts(self):
        p=legacy.ZukoAIOnlyTests().make_presenter(real=True)
        p.ai.format_text=ZukoAI.format_text
        p.gemini_budget.authorize(3,0)
        p.litellm.text=json.dumps({'speech':'Esse mercado virou aventura!','emotion':'AMUSED',
            'intent':'humor','topic':'supermercado_e_economia','animation':'Yes','reply_to':'msg-2'})
        p.monitor.npc.set_speech_hint=Mock()
        legacy.ZukoAIOnlyTests().add_comment(p,'msg-2','Ana','Fui comprar pão e voltei com dez sacolas.')
        self.assertEqual(p.monitor.queued[0].text,'Esse mercado virou aventura!')
        self.assertEqual(p.litellm.calls,1)
        self.assertIn('Retorne JSON compacto',p.litellm.requests[0][0][-1])
        self.assertIn('"source_status": "REAL"',p.litellm.requests[0][0][-2])
        p.monitor.npc.set_speech_hint.assert_called_once_with('msg-2','humor','joy',1)

    def test_hint_waits_for_tts_start_and_uses_existing_selector(self):
        bridge=NPCPanelBridge.__new__(NPCPanelBridge)
        bridge.lock=threading.RLock();bridge.state='ACTIVE';bridge.auto_movements_enabled=True
        bridge.auto_selector=MovementSelector(clock=lambda:10)
        bridge.speech=None;bridge.record=Mock();bridge._movement_record=Mock()
        bridge._new_correlation_id=lambda:'speech-test'
        self.assertTrue(bridge.set_speech_hint('hint-1','support','empathy'))
        self.assertIsNone(bridge.speech)
        response=SimpleNamespace(comment_id='hint-1',text='Estou aqui para acompanhar essa história.')
        bridge.tts('TTS_INICIO',response)
        self.assertEqual(bridge.speech,'hint-1')
        self.assertEqual(bridge.speech_animation,'Wave')
        self.assertEqual(bridge.speech_emotion,'empathy')
        bridge.tts('TTS_OK',response)
        self.assertIsNone(bridge.speech)

    def test_daily_theme_continues_across_turns_and_interruptions(self):
        planner=ContentPlanner();mode=load_config()['modes']['NORMAL']
        first=planner.propose(mode,0)
        self.assertEqual(first.topic,'trabalho_e_correria')
        self.assertIn('cotidiano',first.objective)
        planner.delivered(first,'Fala de teste.',0)
        self.assertEqual(planner.propose(mode,1).topic,first.topic)
        planner.audience_reply_delivered()
        self.assertEqual(planner.propose(mode,2).intent,'resume')

    def test_everyday_chat_is_recognized_without_learning_from_simulation(self):
        memory=AdaptiveMemory(load_config()['memory'])
        memory.observe('COMMENT','sim',text='Como economizar no mercado?',real=False,topic='supermercado_e_economia')
        self.assertEqual(memory.engagement()['data_status'],'UNKNOWN')
        memory.observe('COMMENT','real',text='Como economizar no mercado?',real=True,topic='supermercado_e_economia')
        self.assertEqual(memory.engagement()['related_questions'],1)


if __name__=='__main__':unittest.main()
