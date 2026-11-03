"""Local simulated accounting tests; these tests never call Gemini providers."""
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'npc_runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from zuko_presenter import GeminiSessionBudget
import gemini_limits
import zuko_voice_config as voice_config


class GeminiTextLimitTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.budget = GeminiSessionBudget(min_interval=0, clock=lambda: self.now[0])
        self.budget.reset('text-session')

    def test_saving_limit_preserves_usage_and_applies_to_active_grant(self):
        self.assertEqual(self.budget.authorize(5, 'text-session'), (True, 'authorized'))
        self.assertTrue(self.budget.reserve('text-session')[0])
        self.assertTrue(self.budget.reserve('text-session')[0])
        self.assertEqual(self.budget.snapshot('text-session')['used'], 2)
        self.assertEqual(self.budget.set_limit(4, 'text-session'), (True, 'saved'))
        state = self.budget.snapshot('text-session')
        self.assertTrue(state['authorized'])
        self.assertEqual(state['used'], 2)
        self.assertEqual(state['remaining'], 2)

    def test_unlimited_counts_calls_without_internal_remaining_cap(self):
        self.assertEqual(self.budget.authorize(None, 'text-session'), (True, 'authorized'))
        self.assertTrue(self.budget.reserve('text-session')[0])
        state = self.budget.snapshot('text-session')
        self.assertTrue(state['authorized'])
        self.assertIsNone(state['limit'])
        self.assertIsNone(state['remaining'])
        self.assertEqual(state['used'], 1)

    def test_saving_unlimited_before_session_updates_display_state(self):
        budget = GeminiSessionBudget(min_interval=0, clock=lambda: 100.0)
        budget.set_limit(100)
        self.assertIsNone(budget.epoch)
        self.assertEqual(budget.set_limit(None, epoch=0), (True, 'saved'))
        state = budget.snapshot(0)
        self.assertIsNone(state['limit'])
        self.assertIsNone(state['remaining'])
        self.assertEqual(state['used'], 0)
        self.assertFalse(state['authorized'])

    def test_lowering_limit_below_usage_revokes_only_this_budget(self):
        self.budget.authorize(3, 'text-session')
        self.budget.reserve('text-session')
        self.budget.reserve('text-session')
        self.budget.set_limit(1, 'text-session')
        state = self.budget.snapshot('text-session')
        self.assertFalse(state['authorized'])
        self.assertEqual(state['used'], 2)
        self.assertEqual(state['remaining'], 0)


class GeminiTtsLimitTests(unittest.TestCase):
    def setUp(self):
        self.session_id = 'simulated-' + str(uuid.uuid4())
        voice_config.configure_limit(5)
        voice_config.begin_session(self.session_id)

    def tearDown(self):
        voice_config.end_session(self.session_id)
        voice_config.configure_limit(1)

    def test_mid_session_limit_edit_preserves_used_calls(self):
        voice_config.approve(5)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'SIMULATED_NO_NETWORK'}):
            voice_config.consume()
            voice_config.consume()
        voice_config.configure_limit(4)
        state = voice_config.authorization_status()
        self.assertTrue(state['authorized'])
        self.assertEqual(state['used'], 2)
        self.assertEqual(state['remaining'], 2)

    def test_unlimited_counts_simulated_uses_without_ceiling(self):
        voice_config.approve(None)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'SIMULATED_NO_NETWORK'}):
            voice_config.consume()
        state = voice_config.authorization_status()
        self.assertTrue(state['authorized'])
        self.assertIsNone(state['limit'])
        self.assertIsNone(state['remaining'])
        self.assertEqual(state['used'], 1)

    def test_saving_limit_never_grants_unauthorized_tts(self):
        voice_config.revoke()
        voice_config.configure_limit(None)
        state = voice_config.authorization_status()
        self.assertFalse(state['authorized'])
        self.assertEqual(state['used'], 0)


class GeminiLimitPersistenceTests(unittest.TestCase):
    def test_unlimited_limits_survive_dashboard_reopen(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory:
            path = Path(directory) / 'gemini_limits.json'
            saved = gemini_limits.save_limits(None, None, path)
            self.assertEqual(saved, {'gemini_text': None, 'gemini_tts': None})
            reopened = gemini_limits.load_limits(path)
            self.assertEqual(reopened, saved)
            payload = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(set(payload), {'version', 'gemini_text', 'gemini_tts'})

    def test_distinct_numeric_limits_round_trip(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory:
            path = Path(directory) / 'gemini_limits.json'
            gemini_limits.save_limits(37, 8, path)
            self.assertEqual(gemini_limits.load_limits(path), {'gemini_text': 37, 'gemini_tts': 8})
            gemini_limits.save_limits(22, None, path)
            self.assertEqual(gemini_limits.load_limits(path), {'gemini_text': 22, 'gemini_tts': None})

    def test_save_rejects_values_outside_the_finite_range(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory:
            path = Path(directory) / 'gemini_limits.json'
            for invalid in (0, 101, True, 'ILIMITADO'):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        gemini_limits.save_limits(invalid, 1, path)
            self.assertFalse(path.exists())

    def test_missing_or_invalid_file_uses_defaults(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory:
            path = Path(directory) / 'gemini_limits.json'
            self.assertEqual(gemini_limits.load_limits(path), gemini_limits.DEFAULT_LIMITS)
            path.write_text('{invalid', encoding='utf-8')
            self.assertEqual(gemini_limits.load_limits(path), gemini_limits.DEFAULT_LIMITS)
            path.write_text('{"version":1,"gemini_text":0,"gemini_tts":101}', encoding='utf-8')
            self.assertEqual(gemini_limits.load_limits(path), gemini_limits.DEFAULT_LIMITS)

    def test_start_load_applies_limits_preserves_counters_and_does_not_authorize(self):
        text = GeminiSessionBudget(min_interval=0, clock=lambda: 100.0)
        text.reset('dashboard-session')
        text.authorize(10, 'dashboard-session')
        text.reserve('dashboard-session')
        text.reserve('dashboard-session')
        session_id = 'persistence-' + str(uuid.uuid4())
        voice_config.configure_limit(10)
        voice_config.begin_session(session_id)
        voice_config.approve(10)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'SIMULATED_NO_NETWORK'}):
            voice_config.consume()
            voice_config.consume()
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory:
            path = Path(directory) / 'gemini_limits.json'
            gemini_limits.save_limits(4, 4, path)
            limits, states = gemini_limits.load_and_apply_limits(
                path, text_budget=text, tts_config=voice_config, epoch='dashboard-session')
        self.assertEqual(limits, {'gemini_text': 4, 'gemini_tts': 4})
        self.assertEqual(states['gemini_text']['used'], 2)
        self.assertEqual(states['gemini_text']['remaining'], 2)
        self.assertEqual(states['gemini_tts']['used'], 2)
        self.assertEqual(states['gemini_tts']['remaining'], 2)
        self.assertTrue(states['gemini_text']['authorized'])
        self.assertTrue(states['gemini_tts']['authorized'])
        voice_config.end_session(session_id)

    def test_start_load_keeps_both_services_blocked_without_grants(self):
        text = GeminiSessionBudget(min_interval=0, clock=lambda: 100.0)
        text.reset('new-session')
        session_id = 'blocked-' + str(uuid.uuid4())
        voice_config.configure_limit(1)
        voice_config.begin_session(session_id)
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory:
            path = Path(directory) / 'gemini_limits.json'
            gemini_limits.save_limits(None, None, path)
            _, states = gemini_limits.load_and_apply_limits(
                path, text_budget=text, tts_config=voice_config, epoch='new-session')
        self.assertIsNone(states['gemini_text']['limit'])
        self.assertIsNone(states['gemini_tts']['limit'])
        self.assertFalse(states['gemini_text']['authorized'])
        self.assertFalse(states['gemini_tts']['authorized'])
        voice_config.end_session(session_id)


if __name__ == '__main__':
    unittest.main()
