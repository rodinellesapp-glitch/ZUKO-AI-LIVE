import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from npc_panel_bridge import NPCPanelBridge

class ReconnectTests(unittest.TestCase):
    def make(self):
        b=NPCPanelBridge.__new__(NPCPanelBridge)
        b.runtime=SimpleNamespace(processes=[SimpleNamespace(poll=lambda:None)])
        b.client=Mock();b.stopping=False;b.state='ACTIVE';b.port=18765;b.record=Mock()
        b.audience_queue_provider=lambda:{'version':7,'session':'test','rows':[],'current':{},'extra':0}
        return b
    def test_reconnect_replays_latest_snapshot_without_spawning(self):
        b=self.make();runtime=b.runtime
        self.assertTrue(b._reconnect_transport());self.assertIs(b.runtime,runtime)
        b.client.connect.assert_called_once();b.client.send_audience_queue.assert_called_once_with(b.audience_queue_provider())
    def test_dead_process_is_not_reconnected(self):
        b=self.make();b.runtime.processes[0].poll=lambda:0
        self.assertFalse(b._reconnect_transport());b.client.connect.assert_not_called()
    def test_retry_is_bounded(self):
        b=self.make();b.client.connect.side_effect=ConnectionError('offline')
        with patch('npc_panel_bridge.time.sleep'):self.assertFalse(b._reconnect_transport())
        self.assertEqual(b.client.connect.call_count,3)
    def test_permission_denied_is_not_retried(self):
        b=self.make();error=OSError('denied');error.winerror=10013;b.client.connect.side_effect=error
        self.assertFalse(b._reconnect_transport());self.assertEqual(b.client.connect.call_count,1)
    def test_shutdown_does_not_reconnect(self):
        b=self.make();b.stopping=True
        self.assertFalse(b._reconnect_transport());b.client.connect.assert_not_called()
