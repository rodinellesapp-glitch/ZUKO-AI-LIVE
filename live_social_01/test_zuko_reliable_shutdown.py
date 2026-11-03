import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import zuko_voice_worker
from tts_manager import TTSManager


class FakeStream:
    def __init__(self):
        self.writes=[]
        self.closed=False
    def write(self,value): self.writes.append(value)
    def flush(self): pass
    def close(self): self.closed=True


class FakeProcess:
    def __init__(self, *, graceful=True):
        self.pid=4812
        self.returncode=None
        self.graceful=graceful
        self.stdin=FakeStream();self.stdout=FakeStream();self.stderr=FakeStream()
        self.waits=[];self.kills=0
    def poll(self): return self.returncode
    def wait(self,timeout=None):
        self.waits.append(timeout)
        if self.returncode is not None:return self.returncode
        if self.graceful:
            self.returncode=0
            return 0
        raise subprocess.TimeoutExpired('powershell.exe',timeout)
    def kill(self):
        self.kills+=1
        self.returncode=137


class WorkerShutdownTests(unittest.TestCase):
    def worker_for(self,process,**kwargs):
        worker=zuko_voice_worker.LocalVoiceWorker(**kwargs)
        worker.process=process
        worker.ready=True
        worker.voices=[{'name':'voice'}]
        return worker

    def test_normal_close_requests_protocol_and_is_idempotent(self):
        process=FakeProcess(graceful=True)
        worker=self.worker_for(process)
        result=worker.close()
        second=worker.close()
        self.assertTrue(result['exited']);self.assertEqual(result['status'],'GRACEFUL')
        self.assertEqual(process.stdin.writes,[b'{"op":"close"}\n'])
        self.assertEqual(process.waits,[2.0])
        self.assertTrue(second['exited']);self.assertIsNone(worker.process)
        self.assertEqual(worker.voices,[])
        self.assertTrue(process.stdin.closed and process.stdout.closed and process.stderr.closed)

    def test_stuck_worker_uses_owned_tree_kill_and_does_not_raise_timeout(self):
        process=FakeProcess(graceful=False)
        worker=self.worker_for(process)
        def taskkill(*_args,**_kwargs):
            process.returncode=0
            return SimpleNamespace(returncode=0)
        with mock.patch.object(zuko_voice_worker.os,'name','nt'), \
             mock.patch.object(zuko_voice_worker.subprocess,'run',side_effect=taskkill) as run:
            result=worker.close()
        self.assertTrue(result['exited']);self.assertTrue(result['tree_kill_attempted'])
        self.assertEqual(result['status'],'FORCED')
        self.assertEqual(process.kills,0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][:3],['taskkill','/PID','4812'])
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertIsNone(worker.process)

    def test_taskkill_timeout_falls_back_to_kill_and_bounded_wait(self):
        process=FakeProcess(graceful=False)
        worker=self.worker_for(process,graceful_shutdown_timeout=.2,forced_shutdown_timeout=.3)
        with mock.patch.object(zuko_voice_worker.os,'name','nt'), \
             mock.patch.object(zuko_voice_worker.subprocess,'run',
                               side_effect=subprocess.TimeoutExpired('taskkill',.3)):
            result=worker.close()
        self.assertTrue(result['exited']);self.assertTrue(result['forced'])
        self.assertEqual(result['status'],'FORCED')
        self.assertEqual(process.kills,1)
        self.assertEqual(process.waits,[.2,.3,.3])
        self.assertIsNone(worker.process)


class ManagerCleanupTests(unittest.TestCase):
    def test_close_failure_is_recorded_without_escaping_manager_cleanup(self):
        manager=TTSManager(lambda *_:None,lambda *_:None)
        manager.stopped=True
        fake_voice=SimpleNamespace(falar=lambda *_args,**_kwargs:None)
        fake_worker=SimpleNamespace(close=mock.Mock(side_effect=subprocess.TimeoutExpired('powershell',2)))
        with mock.patch.dict(sys.modules,{
            'zuko_voice':fake_voice,
            'zuko_voice_worker':SimpleNamespace(worker=fake_worker),
        }):
            with self.assertLogs('tts_manager',level='ERROR'):
                manager._drain()
        snapshot=manager.snapshot()
        self.assertEqual(snapshot['TTS_WORKER_CLOSE']['status'],'CLOSE_ERROR')
        self.assertEqual(snapshot['TTS_WORKER_CLOSE']['error_type'],'TimeoutExpired')
        self.assertEqual(manager.state,manager.IDLE)

    def test_enqueue_still_preserves_serial_priority_queue(self):
        manager=TTSManager(lambda *_:None,lambda *_:None)
        low=SimpleNamespace(author='Ana',comment_id='low',source='LIVE_YOUTUBE',tts_priority=1,
                            provider='',text='fala baixa',received_at=0,tts_enabled=True)
        high=SimpleNamespace(author='Bia',comment_id='high',source='LIVE_YOUTUBE',tts_priority=3,
                             provider='',text='presente',received_at=0,tts_enabled=True)
        class StubThread:
            starts=0
            def __init__(self,*_args,**_kwargs):pass
            def start(self):self.starts+=1
            def is_alive(self):return True
        with mock.patch.object(threading,'Thread',StubThread):
            manager.enqueue(low);manager.enqueue(high)
        self.assertEqual([item.response.comment_id for item in manager.queue],['high','low'])
        self.assertEqual(manager.snapshot()['TTS_QUEUE_DEPTH'],2)
        self.assertEqual(manager.worker.starts,1)


if __name__=='__main__':
    unittest.main()
