import threading
import unittest
import test_zuko_ai_only as fixtures
from test_zuko_ai_only import FakeAI
from live_moderator import LiveModeratorManager

class StabilityTests(unittest.TestCase):
    make_presenter = fixtures.ZukoAIOnlyTests.make_presenter
    unit = staticmethod(fixtures.ZukoAIOnlyTests.unit)
    add_comment = fixtures.ZukoAIOnlyTests.add_comment

    def test_single_suppression(self):
        p=self.make_presenter(ai=FakeAI(error='offline'))
        self.add_comment(p,'failed','Ana','Como funciona?')
        self.assertEqual(sum(r['event']=='AI_SPEECH_SUPPRESSED' for r in p.history),1)
        self.assertFalse(p.monitor.queued)

    def test_timeout_discards_late_result_and_keeps_lock(self):
        gate=threading.Event()
        class Slow(FakeAI):
            def response(self,event):
                gate.wait(2)
                return super().response(event)
        p=self.make_presenter(ai=Slow());p.generation_budget=.02
        try:
            self.add_comment(p,'slow','Ana','Pergunta?')
            self.assertTrue(p.inference_lock.locked())
            self.assertFalse(p.monitor.queued)
            self.assertEqual(sum(r['event']=='AI_SPEECH_SUPPRESSED' for r in p.history),1)
        finally: gate.set()
        self.assertTrue(p.inference_lock.acquire(timeout=1));p.inference_lock.release()
        self.assertFalse(p.monitor.queued)

    def test_busy_recovery(self):
        p=self.make_presenter();p.inference_lock.acquire()
        timer=threading.Timer(.02,p.inference_lock.release);timer.start()
        self.assertTrue(p._acquire_inference(self.unit('wait'),0))
        p.inference_lock.release();timer.join()

    def test_cancelled_wait(self):
        p=self.make_presenter();p.paused=True
        self.assertFalse(p._acquire_inference(self.unit('cancel'),0))

    def test_repeat_and_spam(self):
        now=[0.0];m=LiveModeratorManager(clock=lambda:now[0])
        self.assertFalse(m.analyze('Ana','sim').suppress)
        second=m.analyze('Ana','sim')
        self.assertFalse(second.suppress);self.assertTrue(second.presenter_allowed)
        self.assertTrue(m.analyze('Ana','sim').suppress)
        self.assertFalse(m.analyze('Bia','sim').suppress)
        now[0]=11
        self.assertFalse(m.analyze('Ana','sim').suppress)

    def test_autonomous_animation(self):
        p=self.make_presenter()
        p.dispatch(self.unit('auto',source='PRESENTER',metadata={'zuko_auto':True}))
        self.assertEqual(len(p.monitor.queued),1)
        self.assertTrue(p.monitor.npc.events)
        self.assertEqual(p.stats['ZUKO_RULE_TEXTS'],0)
