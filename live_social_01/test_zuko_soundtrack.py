from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import tempfile
import threading
import time
import unittest
import wave

from zuko_soundtrack import DEFAULT,Preferences,SoundtrackController,local_audio_path


class Clock:
    def __init__(self):self.now=0.
    def __call__(self):return self.now
    def advance(self,value):self.now+=value


class FakeMusicBackend:
    def __init__(self):
        self.state='closed';self.path='';self.volume=0.;self.calls=[];self.history=[]
    def open(self,path):
        self.close();self.calls.append(('open',str(path)))
        if Path(path).stem.startswith('bad'):raise RuntimeError('invalid audio')
        self.path=str(path);self.state='stopped';self.volume=0
    def play(self):self.state='playing';self.calls.append(('play',self.path))
    def pause(self):self.state='paused';self.calls.append(('pause',self.path))
    def resume(self):self.state='playing';self.calls.append(('resume',self.path))
    def mode(self):return self.state
    def set_volume(self,value):
        self.volume=value;self.history.append((time.monotonic(),value));self.calls.append(('volume',value))
    def close(self):
        if self.path:self.calls.append(('close',self.path))
        self.path='';self.state='closed'


class SoundtrackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.clock=Clock();self.backend=FakeMusicBackend()
        self.controller=SoundtrackController(None,backend_factory=lambda:self.backend,clock=self.clock,threaded=False)
        self.addCleanup(self.controller.close)
        self.first=self.directory/'first.wav';self.second=self.directory/'second.mp3'
        self.first.write_bytes(b'test');self.second.write_bytes(b'test')
        self.response=SimpleNamespace(comment_id='voice-1')

    def playing(self):
        self.controller.add_files([self.first,self.second],licensed=True)
        self.controller.start();self.controller.step();self.clock.advance(.8);self.controller.step()
        self.assertAlmostEqual(self.controller.volume,35)

    def duck(self):
        self.controller.tts_event('TTS_INICIO',self.response,snapshot={'TTS_STATE':'PLAYING'})
        self.controller.step();self.clock.advance(.3);self.controller.step()
        self.assertAlmostEqual(self.controller.volume,8)

    def test_defaults_and_loaded_playlist_never_autostart(self):
        path=self.directory/'settings.json';value=dict(DEFAULT)
        value['playlist']=[{'path':str(self.first),'licensed':True}]
        Preferences(path).save(value)
        controller=SoundtrackController(path,backend_factory=lambda:self.backend)
        self.addCleanup(controller.close)
        self.assertFalse(controller.enabled);self.assertIsNone(controller.worker)
        self.assertEqual(controller.snapshot()['preferences']['normal_volume'],35)
        self.assertEqual(self.backend.calls,[])

    def test_local_formats_rights_and_duplicates(self):
        with self.assertRaises(ValueError):self.controller.add_files([self.first])
        for value in ('https://example.com/music.mp3','\\\\server\\share\\music.wav',str(self.directory/'music.exe')):
            with self.subTest(path=value),self.assertRaises(ValueError):local_audio_path(value)
        self.controller.add_files([self.first,self.first,self.second],licensed=True)
        self.assertEqual(len(self.controller.preferences['playlist']),2)
        self.assertFalse(self.controller.enabled)

    def test_synthesis_alone_does_not_duck(self):
        self.playing()
        self.controller.tts_event('TTS_STATE',detail='SYNTHESIZING',snapshot={'TTS_STATE':'SYNTHESIZING'})
        self.clock.advance(10);self.controller.step()
        self.assertAlmostEqual(self.controller.volume,35)

    def test_duck_ramp_is_300ms(self):
        self.playing()
        self.controller.tts_event('TTS_INICIO',self.response,snapshot={'TTS_STATE':'PLAYING'})
        self.controller.step();self.clock.advance(.15);self.controller.step()
        self.assertAlmostEqual(self.controller.volume,21.5)
        self.clock.advance(.15);self.controller.step();self.assertAlmostEqual(self.controller.volume,8)

    def test_restore_waits_short_hold_then_fades_800ms(self):
        self.playing();self.duck()
        self.controller.tts_event('TTS_OK',self.response,snapshot={'TTS_STATE':'IDLE','TTS_QUEUE_DEPTH':0})
        self.clock.advance(.3);self.controller.step();self.assertAlmostEqual(self.controller.volume,8)
        self.clock.advance(.051);self.controller.step()
        self.clock.advance(.4);self.controller.step();self.assertAlmostEqual(self.controller.volume,21.5)
        self.clock.advance(.4);self.controller.step();self.assertAlmostEqual(self.controller.volume,35)

    def test_consecutive_speech_keeps_low_volume_during_next_synthesis(self):
        self.playing();self.duck()
        self.controller.tts_event('TTS_OK',self.response,snapshot={'TTS_STATE':'IDLE','TTS_QUEUE_DEPTH':1})
        self.clock.advance(2);self.controller.step();self.assertAlmostEqual(self.controller.volume,8)
        self.controller.tts_event('TTS_STATE',detail='SYNTHESIZING',snapshot={'TTS_STATE':'SYNTHESIZING','TTS_QUEUE_DEPTH':0})
        self.clock.advance(10);self.controller.step();self.assertAlmostEqual(self.controller.volume,8)
        second=SimpleNamespace(comment_id='voice-2');self.controller.before_voice(second)
        self.controller.tts_event('TTS_INICIO',second,snapshot={'TTS_STATE':'PLAYING'})
        self.clock.advance(1);self.controller.step();self.assertAlmostEqual(self.controller.volume,8)

    def test_dropped_queued_item_does_not_release_current_voice(self):
        self.playing();self.duck()
        self.controller.tts_event('TTS_STALE_DROPPED',SimpleNamespace(comment_id='other'),snapshot={'TTS_STATE':'PLAYING'})
        self.clock.advance(2);self.controller.step()
        self.assertTrue(self.controller.voice_active);self.assertAlmostEqual(self.controller.volume,8)

    def test_cancel_error_and_idle_restore_without_affecting_voice(self):
        for terminal in ('TTS_CANCELLED','TTS_ERRO'):
            with self.subTest(event=terminal):
                self.playing();self.duck()
                self.controller.tts_event(terminal,self.response,snapshot={'TTS_STATE':'IDLE'})
                self.clock.advance(.36);self.controller.step()
                self.clock.advance(.81);self.controller.step()
                self.assertAlmostEqual(self.controller.volume,35)

    def test_pause_resume_mute_and_queued_tts_pause(self):
        self.playing();self.duck()
        self.controller.pause();self.controller.step();self.assertEqual(self.backend.state,'paused')
        self.controller.set_mute(True);self.controller.step();self.assertEqual(self.backend.volume,0)
        self.controller.resume();self.controller.step();self.assertEqual(self.backend.volume,0)
        self.assertEqual(self.backend.state,'playing')
        self.controller.set_mute(False);self.controller.step();self.clock.advance(.81);self.controller.step()
        self.assertAlmostEqual(self.controller.volume,8)
        self.controller.tts_event('TTS_STATE',detail='IDLE',snapshot={'TTS_STATE':'IDLE','TTS_QUEUE_DEPTH':2,'TTS_PAUSED':True})
        self.clock.advance(.36);self.controller.step();self.clock.advance(.81);self.controller.step()
        self.assertAlmostEqual(self.controller.volume,35)

    def test_playlist_order_loop_and_single_player(self):
        self.playing()
        self.backend.state='stopped';self.clock.advance(.06);self.controller.step()
        self.assertEqual(Path(self.controller.current_path),self.second)
        self.backend.state='stopped';self.clock.advance(.06);self.controller.step()
        self.assertEqual(Path(self.controller.current_path),self.first)
        self.assertEqual(self.controller.counts['playlist_loops'],1)
        self.controller.move(0,1);self.controller.step()
        self.assertEqual(self.controller.selected,1)
        self.controller.remove(1);self.controller.step()
        self.assertEqual(Path(self.controller.current_path),self.second)
        self.controller.clear();self.controller.step();self.assertFalse(self.controller.enabled)

    def test_bad_tracks_are_skipped_without_retry_storm(self):
        bad=self.directory/'bad.wav';bad.write_bytes(b'bad')
        self.controller.add_files([bad,self.first],licensed=True)
        self.controller.start();self.controller.step()
        for _ in range(20):
            self.backend.state='stopped';self.clock.advance(.1);self.controller.step()
        opens=[value for key,value in self.backend.calls if key=='open' and value==str(bad)]
        self.assertEqual(len(opens),1);self.assertTrue(self.controller.enabled)

    def test_all_bad_tracks_stop_with_error(self):
        bad=self.directory/'bad.wav';bad.write_bytes(b'bad')
        self.controller.add_files([bad],licensed=True);self.controller.start();self.controller.step()
        count=len(self.backend.calls)
        for _ in range(100):self.clock.advance(.1);self.controller.step()
        self.assertFalse(self.controller.enabled);self.assertEqual(self.controller.state,'ERROR')
        self.assertEqual(count,len(self.backend.calls))

    def test_preferences_round_trip_and_validation(self):
        path=self.directory/'settings.json'
        controller=SoundtrackController(path,threaded=False);self.addCleanup(controller.close)
        controller.save_levels(40,9,300,800);controller.set_mute(True)
        loaded=SoundtrackController(path,threaded=False);self.addCleanup(loaded.close)
        self.assertFalse(loaded.enabled);self.assertTrue(loaded.preferences['mute'])
        self.assertEqual(loaded.preferences['normal_volume'],40)
        self.assertNotIn('enabled',json.loads(path.read_text()))
        with self.assertRaises(ValueError):loaded.save_levels(10,30)

    def test_corrupt_preferences_preserved_on_explicit_save(self):
        path=self.directory/'settings.json';path.write_text('invalid')
        store=Preferences(path);self.assertEqual(store.load()['normal_volume'],35)
        store.save(DEFAULT)
        self.assertEqual(path.with_suffix('.previous.json').read_text(),'invalid')

    def test_threaded_gate_finishes_before_voice_and_close_joins_worker(self):
        backend=FakeMusicBackend();controller=SoundtrackController(None,backend_factory=lambda:backend)
        self.addCleanup(controller.close)
        controller.add_files([self.first],licensed=True);controller.save_levels(35,8,50,20)
        controller.start();deadline=time.monotonic()+1
        while controller.volume<34.9 and time.monotonic()<deadline:time.sleep(.005)
        self.assertGreater(controller.volume,34.9)
        controller.tts_event('TTS_STATE',detail='SYNTHESIZING')
        self.assertTrue(controller.before_voice(self.response))
        self.assertLessEqual(controller.volume,8.15)
        self.assertTrue(controller.close());self.assertFalse(controller.snapshot()['worker_alive'])
        self.assertEqual(backend.state,'closed')


class PlaybackHookTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'npc_runtime'))

    def test_maria_hook_order_is_synthesis_then_duck_then_play(self):
        import zuko_voice
        order=[]
        def maria(_text,**kwargs):
            order.append('synthesizing');order.append('ready')
            kwargs['on_synthesized']();order.append('play')
            kwargs['on_playback_started']()
        with patch.object(zuko_voice,'maria_speak',maria):
            zuko_voice.falar('Teste local.',voice_config={'engine':'Microsoft Maria'},
                on_synthesized=lambda:order.append('synthesized'),
                before_playback=lambda:order.append('duck_ready'),
                on_playback_started=lambda:order.append('playing'))
        self.assertEqual(order,['synthesizing','ready','synthesized','duck_ready','play','playing'])

    def test_cancel_during_preplay_never_calls_play(self):
        import zuko_voice
        cancelled=threading.Event();order=[]
        def maria(_text,**kwargs):
            kwargs['on_synthesized']();order.append('play')
        with patch.object(zuko_voice,'maria_speak',maria):
            zuko_voice.falar('Teste local.',cancelar=cancelled.is_set,voice_config={'engine':'Microsoft Maria'},
                before_playback=cancelled.set)
        self.assertEqual(order,[])

    def test_preview_uses_hook_after_load_before_play(self):
        import zuko_voice
        order=[]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'preview.wav'
            with wave.open(str(path),'wb') as handle:
                handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(8000);handle.writeframes(bytes(160))
            busy=iter([True,False])
            music=SimpleNamespace(load=lambda _path:order.append('load'),set_volume=lambda _volume:None,
                play=lambda:order.append('play'),get_busy=lambda:next(busy),stop=lambda:None,unload=lambda:None)
            mixer=SimpleNamespace(get_init=lambda:True,music=music)
            with patch.object(zuko_voice.pygame,'mixer',mixer):
                zuko_voice.falar('Amostra local.',preview_audio_path=str(path),
                    before_playback=lambda:order.append('duck_ready'),on_playback_started=lambda:order.append('playing'))
        self.assertEqual(order,['load','duck_ready','play','playing'])

    def test_serial_tts_uses_real_play_callback_once_and_preserves_low_music(self):
        import zuko_voice
        import tts_manager
        from live_response import LiveResponse
        events=[];started=threading.Event();allow=threading.Event();second_synth=threading.Event()
        music=SoundtrackController(None,backend_factory=FakeMusicBackend)
        self.addCleanup(music.close)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'tone.wav';path.write_bytes(b'test')
            music.add_files([path],licensed=True);music.save_levels(35,8,30,40);music.start()
            deadline=time.monotonic()+1
            while music.volume<34.9 and time.monotonic()<deadline:time.sleep(.005)
            manager=None
            def tts_event(event,response=None,detail=''):
                events.append((event,getattr(response,'comment_id',None)))
                music.tts_event(event,response,detail,manager.snapshot() if manager else {})
            manager=tts_manager.TTSManager(lambda *_:None,lambda *_:None,tts_event,
                before_playback=music.before_voice)
            self.addCleanup(manager.stop)
            calls=[]
            def fake_voice(_text,**kwargs):
                calls.append(1)
                if len(calls)==1:started.set();allow.wait(1)
                else:
                    second_synth.set();time.sleep(.12)
                    self.assertLessEqual(music.volume,8.2)
                kwargs['on_synthesized']();kwargs['before_playback']()
                self.assertLessEqual(music.volume,8.2)
                kwargs['on_playback_started']();time.sleep(.02)
            with patch.object(zuko_voice,'falar',fake_voice),patch.object(tts_manager.pygame.mixer,'get_init',lambda:False):
                first=LiveResponse('one','Ana','Primeira.','ZUKO_GEMINI',0,time.monotonic(),'ZUKO',True)
                second=LiveResponse('two','Bia','Segunda.','ZUKO_GEMINI',0,time.monotonic(),'ZUKO',True)
                manager.enqueue(first);self.assertTrue(started.wait(1));manager.enqueue(second);allow.set()
                deadline=time.monotonic()+3
                while sum(event=='TTS_OK' for event,_ in events)<2 and time.monotonic()<deadline:time.sleep(.005)
                self.assertEqual(sum(event=='TTS_OK' for event,_ in events),2)
                self.assertEqual(sum(event=='TTS_INICIO' for event,_ in events),2)
                self.assertTrue(second_synth.is_set())
                manager.stop()
                if manager.worker:manager.worker.join(1)


if __name__=='__main__':unittest.main()
