from pathlib import Path
import json
import tempfile
import threading
import unittest
from zuko_v3_content import FRAMES
from zuko_v3_learning import EvidenceStore,ReflectionWorker,validate_reflection


def summary(real=True):
    return {'source_observed':real,'frames':{FRAMES[0]:{'completed':4,'related_questions':2}},
        'topics':['robotica'],'totals':{'completed':4},'technical_failures':{},'association_only':True}


class LearningTests(unittest.TestCase):
    def test_recurrence_and_review_required_before_weight_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'learning.json';store=EvidenceStore(path)
            for index in range(3):self.assertTrue(store.add_session(f'{index:032x}',summary()))
            self.assertEqual(store.weights(),{})
            self.assertEqual(store.snapshot()['patterns'][FRAMES[0]]['status'],'pending')
            self.assertTrue(store.review(FRAMES[0],True))
            restarted=EvidenceStore(path)
            self.assertEqual(restarted.weights(),{FRAMES[0]:1.1})
            self.assertNotIn('speech',path.read_text())

    def test_simulation_and_repeated_same_session_never_promote(self):
        store=EvidenceStore()
        for index in range(8):store.add_session(f'{index:032x}',summary(False))
        self.assertEqual(store.snapshot()['patterns'],{})
        self.assertFalse(store.add_session(f'{1:032x}',summary()))

    def test_corrupt_or_sensitive_store_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'learning.json';path.write_text('{"token":"secret"}')
            store=EvidenceStore(path)
            self.assertTrue(store.error)
            self.assertFalse(store.add_session('a'*32,summary()))
            self.assertEqual(path.read_text(),'{"token":"secret"}')

    def test_reflection_is_cancelled_and_cannot_execute_arbitrary_actions(self):
        worker=ReflectionWorker();started=threading.Event()
        def model(_context,cancelled):
            started.set()
            while not cancelled():threading.Event().wait(.001)
            return {'action':'execute','topic':'robotica','energy':'higher','reason_code':'CONTINUITY'}
        self.assertTrue(worker.start({'topic':'robotica'},model));self.assertTrue(started.wait(1))
        self.assertTrue(worker.close());self.assertIsNone(worker.poll())
        with self.assertRaises(ValueError):validate_reflection({'action':'execute','topic':'robotica',
            'energy':'higher','reason_code':'CONTINUITY'})

    def test_reflection_cache_and_bounded_session_history(self):
        worker=ReflectionWorker();context={'topic':'robotica','engagement':{'data_status':'UNKNOWN'}}
        worker.start(context);worker.worker.join(1)
        first=worker.poll();worker.start(context);self.assertEqual(worker.poll(),first)
        self.assertTrue(worker.close())
        store=EvidenceStore(config={'history_sessions':3})
        for index in range(30):store.add_session(f'{index:032x}',summary(False))
        self.assertEqual(store.snapshot()['sessions'],3)


if __name__=='__main__':unittest.main()
