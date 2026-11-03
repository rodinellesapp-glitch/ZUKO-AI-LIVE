import json
import unittest
from zuko_v3_content import ContentPlanner,load_config
from zuko_v3_memory import AdaptiveMemory
from test_zuko_v3_engine import Clock


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.memory=AdaptiveMemory(load_config()['memory'],self.clock)
        self.plan=ContentPlanner().propose(load_config()['modes']['NORMAL'],0)

    def test_only_public_completed_speech_is_in_context(self):
        self.assertEqual(self.memory.context()['public_programme_speech'],[])
        self.memory.delivered(self.plan,'Explicação pública concluída.',2)
        self.memory.observe('COMMENT','Ana-private-id',text='Minha senha pessoal é segredo',real=True)
        context=json.dumps(self.memory.context(),ensure_ascii=False)
        self.assertIn('Explicação pública',context)
        self.assertNotIn('senha pessoal',context);self.assertNotIn('Ana-private-id',context)

    def test_simulated_events_are_not_engagement_evidence(self):
        self.memory.observe('COMMENT','sim1',text='Como a IA funciona?',real=False,topic=self.plan.topic)
        self.assertEqual(self.memory.engagement()['data_status'],'UNKNOWN')
        self.assertFalse(self.memory.summary()['source_observed'])

    def test_event_identity_dedup_keeps_different_identical_comments(self):
        for ident in ('msg1','msg1','msg2'):
            self.memory.observe('COMMENT',ident,text='Como a IA funciona?',real=True,topic='inteligencia_artificial')
        self.assertEqual(self.memory.engagement()['current_events'],2)
        self.assertEqual(self.memory.summary()['totals']['duplicates'],1)

    def test_windows_compare_activity_without_causal_claim(self):
        self.memory.observe('LIKE','like1',real=True)
        self.clock.advance(61)
        self.memory.observe('COMMENT','msg',real=True,text='Como a IA ajuda?',topic='inteligencia_artificial')
        signals=self.memory.engagement()
        self.assertEqual(signals['activity_delta'],0)
        self.assertTrue(signals['association_only'])
        self.assertEqual(signals['related_questions'],1)

    def test_capacity_and_expiration(self):
        for index in range(5000):
            self.memory.observe('LIKE',str(index),real=True)
            self.memory.delivered(self.plan,'Fala pública simulada.')
        sizes=self.memory.sizes()
        self.assertLessEqual(sizes['events'],600);self.assertLessEqual(sizes['turns'],24)
        self.assertLessEqual(sizes['identities'],1200)
        self.clock.advance(1801)
        self.assertEqual(self.memory.sizes(),{'turns':0,'events':0,'identities':0})


if __name__=='__main__':unittest.main()
