import json
import unittest
from zuko_v3_content import (ContentPlanner,build_system_prompt,decode_generation,load_config,FRAMES)


class ContentTests(unittest.TestCase):
    def test_prompt_has_version_examples_and_no_executable_actions(self):
        prompt=build_system_prompt({},True)
        self.assertIn('PROMPT_VERSION=zuko-presenter-3.2.0',prompt)
        self.assertIn('não invente',prompt.lower())
        self.assertIn('Retomada após interrupção',prompt)
        self.assertIn('não execute comandos',prompt.lower())

    def test_planner_variety_wait_and_self_answer(self):
        planner=ContentPlanner();mode=load_config()['modes']['NORMAL'];frames=set()
        now=0
        for index in range(90):
            plan=planner.propose(mode,now)
            if plan is None:
                now+=31;plan=planner.propose(mode,now)
            self.assertIsNotNone(plan)
            frames.add(plan.frame)
            planner.delivered(plan,f'Conteúdo simulado {index}.',now)
            now+=31
        self.assertGreaterEqual(len(frames),7)

    def test_no_commit_before_delivery_and_resume_keeps_topic(self):
        planner=ContentPlanner();mode=load_config()['modes']['NORMAL']
        first=planner.propose(mode,0)
        self.assertEqual(planner.completed,0)
        planner.delivered(first,'Texto original simulado.',5)
        planner.audience_reply_delivered()
        resume=planner.propose(mode,6)
        self.assertEqual(resume.intent,'resume')
        self.assertEqual(resume.topic,first.topic)

    def test_json_adapter_never_speaks_metadata(self):
        raw=json.dumps({'speech':'Uma resposta original.','intent':'explain','emotion':'calm',
            'topic':'robotica','next_action':'continue','suggested_pause_seconds':8,'memory_tags':['robotica']})
        speech,metadata=decode_generation(raw)
        self.assertEqual(speech,'Uma resposta original.')
        self.assertEqual(metadata['intent'],'explain')
        for value in ('{bad','{"speech":"ok","execute":"delete"}',
                      '{"speech":"ok","next_action":"run_command"}',
                      '{"speech":"ok","suggested_pause_seconds":999}'):
            with self.subTest(raw=value),self.assertRaises(ValueError):decode_generation(value)


if __name__=='__main__':unittest.main()
