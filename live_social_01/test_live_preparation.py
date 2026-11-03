import unittest

from live_preparation import LivePreparationController, tiktok_event_readiness_lines


class FakeRoot:
    def __init__(self):
        self.pending = []

    def after(self, _delay, callback):
        self.pending.append(callback)
        return len(self.pending)

    def run_next(self):
        callback = self.pending.pop(0)
        callback()


class FakeNPC:
    def __init__(self, state="OFF"):
        self.state = state
        self.opens = 0
        self.closes = 0

    def open(self):
        self.opens += 1
        self.state = "STARTING"

    def close_npc(self):
        self.closes += 1
        self.state = "CLOSING"


class FakeMonitor:
    def __init__(self, npc_state="OFF", reading=False, local_test_mode=False, source="tiktok-sim"):
        self.npc = FakeNPC(npc_state)
        self.reading = reading
        self.local_test_mode = local_test_mode
        self.source = source


class LivePreparationTests(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.monitor = FakeMonitor()
        self.updates = []
        self.started = 0
        self.stopped = 0
        self.controller = LivePreparationController(
            self.root,
            lambda: self.monitor,
            lambda state, detail: self.updates.append((state, detail)),
            self.start_source,
            self.stop_source,
            timeout_seconds=1,
            clock=lambda: 0,
        )

    def start_source(self):
        self.started += 1
        self.monitor.reading = True

    def stop_source(self):
        self.stopped += 1
        self.monitor.reading = False

    def test_waits_for_godot_then_starts_selected_source_once(self):
        self.assertTrue(self.controller.start())
        self.assertFalse(self.controller.start())
        self.assertEqual(self.monitor.npc.opens, 1)
        self.assertEqual(self.started, 0)
        self.monitor.npc.state = "ACTIVE"
        self.root.run_next()
        self.assertEqual(self.controller.state, "READY")
        self.assertEqual(self.started, 1)
        self.assertIn("ponte local confirmada", self.controller.detail)

    def test_local_test_does_not_start_external_source(self):
        self.monitor.local_test_mode = True
        self.monitor.reading = True
        self.assertTrue(self.controller.start())
        self.monitor.npc.state = "ACTIVE"
        self.root.run_next()
        self.assertEqual(self.controller.state, "READY")
        self.assertEqual(self.started, 0)
        self.assertIn("teste local", self.controller.detail)

    def test_cancel_closes_only_components_started_by_preparation(self):
        self.assertTrue(self.controller.start())
        self.assertTrue(self.controller.cancel())
        self.assertEqual(self.monitor.npc.closes, 1)
        self.assertEqual(self.stopped, 0)
        self.assertEqual(self.controller.state, "CANCELLED")
        self.root.run_next()
        self.assertEqual(self.monitor.npc.opens, 1)

    def test_preexisting_npc_and_reader_are_not_restarted_or_closed(self):
        self.monitor = FakeMonitor(npc_state="ACTIVE", reading=True, source="tiktok")
        self.controller.monitor_provider = lambda: self.monitor
        self.assertTrue(self.controller.start())
        self.root.run_next()
        self.assertEqual(self.monitor.npc.opens, 0)
        self.assertEqual(self.started, 0)
        self.assertEqual(self.controller.state, "READY")

    def test_godot_error_fails_without_starting_source(self):
        self.assertTrue(self.controller.start())
        self.monitor.npc.state = "ERROR"
        self.root.run_next()
        self.assertEqual(self.controller.state, "FAILED")
        self.assertEqual(self.started, 0)

    def test_source_start_failure_stops_the_partial_reader_and_owned_npc(self):
        self.assertTrue(self.controller.start())
        self.monitor.npc.state = "ACTIVE"

        def partial_failure():
            self.monitor.reading = True
            raise RuntimeError("simulated source failure")

        self.controller.start_source = partial_failure
        self.root.run_next()
        self.assertEqual(self.controller.state, "FAILED")
        self.assertEqual(self.stopped, 1)
        self.assertEqual(self.monitor.npc.closes, 1)

    def test_tiktok_readiness_reports_supported_unverified_and_verified_events(self):
        lines = tiktok_event_readiness_lines({
            "TIKTOK_CONNECTION": "CONNECTED",
            "TIKTOK_CHAT": "ONLINE", "TIKTOK_CHAT_VALIDATION": "VERIFIED_REAL",
            "TIKTOK_GIFTS": "ONLINE", "TIKTOK_GIFTS_VALIDATION": "SUPPORTED_UNVERIFIED",
            "TIKTOK_FOLLOWS": "ONLINE", "TIKTOK_FOLLOWS_VALIDATION": "SUPPORTED_UNVERIFIED",
            "TIKTOK_LIKES": "ONLINE", "TIKTOK_LIKES_VALIDATION": "SUPPORTED_UNVERIFIED",
            "TIKTOK_CHAT_RECEIVED": 2, "TIKTOK_GIFTS_RECEIVED": 1,
            "TIKTOK_FOLLOWS_RECEIVED": 0, "TIKTOK_LIKES_RECEIVED": 3,
        })
        report = "\n".join(lines)
        self.assertIn("Leitor TikTok: conectado (CONNECTED)", report)
        self.assertIn("Comentários: validação real confirmada · contagem: 2", report)
        self.assertIn("Presentes: suportado, ainda sem validação real · contagem: 1", report)
        self.assertIn("Seguidores: suportado, ainda sem validação real · contagem: 0", report)
        self.assertIn("Curtidas: suportado, ainda sem validação real · contagem: 3", report)

    def test_tiktok_readiness_does_not_claim_simulator_or_pending_source_is_real(self):
        simulated = "\n".join(tiktok_event_readiness_lines({
            "TIKTOK_CONNECTION": "SIMULATOR", "TIKTOK_CHAT": "SIMULATOR",
            "TIKTOK_GIFTS": "SIMULATOR", "TIKTOK_FOLLOWS": "SIMULATOR",
            "TIKTOK_LIKES": "SIMULATOR",
        }))
        self.assertEqual(simulated.count("simulado, sem validação real"), 4)
        pending = "\n".join(tiktok_event_readiness_lines({
            "TIKTOK_CONNECTION": "WAITING_FOR_LIVE",
        }))
        self.assertEqual(pending.count("aguardando detecção do adaptador"), 4)


if __name__ == "__main__":
    unittest.main()
