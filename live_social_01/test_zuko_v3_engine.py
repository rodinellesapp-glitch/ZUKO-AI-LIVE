import unittest
from zuko_v3_engine import AutonomousEngine


class Clock:
    def __init__(self):self.now=0.
    def __call__(self):return self.now
    def advance(self,value):self.now+=value


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.engine=AutonomousEngine(clock=self.clock)

    def request(self,**kwargs):
        return self.engine.request(**{'tts_idle':True,'director_busy':False,'npc_ready':True,**kwargs})

    def test_off_by_default_and_single_pending(self):
        self.assertIsNone(self.request());self.engine.enable(True)
        ident,plan=self.request();self.assertIsNone(self.request())
        self.assertEqual(self.engine.snapshot()['completed'],0)
        self.engine.completed(ident,'Fala simulada.')
        self.assertEqual(self.engine.snapshot()['completed'],1)
        self.assertIsNone(self.request());self.clock.advance(26)
        self.assertIsNotNone(self.request())

    def test_devices_priority_pause_and_close(self):
        self.engine.enable(True)
        for key in ('director_busy','godot_speaking'):
            self.assertIsNone(self.request(**{key:True}))
        self.assertIsNone(self.request(tts_idle=False));self.assertIsNone(self.request(npc_ready=False))
        self.engine.pause(True);self.assertIsNone(self.request())
        self.engine.close();self.assertFalse(self.engine.enable(True))

    def test_budget_reserve_rate_limit_and_circuit_do_not_change_grant(self):
        budget={'authorized':True,'remaining':10,'used':3}
        self.assertEqual(self.engine.allow_gemini(budget)[1],'AUDIENCE_RESERVE')
        budget['remaining']=30
        self.assertTrue(self.engine.allow_gemini(budget)[0])
        self.engine.gemini_started();self.engine.gemini_started()
        self.assertEqual(self.engine.allow_gemini(budget)[1],'AUTONOMOUS_RATE_LIMIT')
        self.clock.advance(61)
        for _ in range(3):self.engine.provider_result(False)
        self.assertEqual(self.engine.allow_gemini(budget)[1],'CIRCUIT_OPEN')
        self.assertEqual(budget,{'authorized':True,'remaining':30,'used':3})

    def test_failed_generation_does_not_advance_programme(self):
        self.engine.enable(True);ident,plan=self.request();self.engine.failed(ident,'PROVIDER_ERROR')
        self.assertEqual(self.engine.planner.completed,0)
        self.assertIsNone(self.request());self.clock.advance(16)
        self.assertIsNotNone(self.request())


if __name__=='__main__':unittest.main()
