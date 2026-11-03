"""Offline evidence and protocol regressions; never grants a real TCP pass."""
from pathlib import Path
import importlib.util
import json
import os
import tempfile
import unittest
from unittest.mock import Mock,patch

from bridge_diagnostics import exception_details,process_context
from show_tcp import ShowClient

ROOT=Path(__file__).resolve().parents[1]


class BridgeEvidenceTests(unittest.TestCase):
    def test_nested_error_keeps_winerror_endpoint_pid_and_full_traceback(self):
        try:
            try:
                error=PermissionError('test only');error.winerror=10013
                raise error
            except PermissionError as cause:raise ConnectionError('wrapped transport') from cause
        except ConnectionError as error:
            details=exception_details(error,phase='test',operation='connect')
        self.assertEqual(details['operation'],'connect')
        self.assertEqual(details['endpoint']['ip'],'127.0.0.1')
        self.assertEqual(details['endpoint']['port'],18765)
        self.assertEqual(details['process']['pid'],os.getpid())
        self.assertEqual(details['exceptions'][-1]['winerror'],10013)
        self.assertIn('PermissionError',details['traceback'])
        self.assertIn('ConnectionError',details['traceback'])
        self.assertIn('direct cause',details['traceback'])
        json.dumps(details)
    def test_context_does_not_collect_credentials_or_command_arguments(self):
        context=process_context()
        self.assertEqual(context['pid'],os.getpid())
        self.assertNotIn('environment',context);self.assertNotIn('command_line',context)
        if os.name=='nt':self.assertIn('app_container',context)
    def test_animation_and_idle_wire_format_remain_json_lines(self):
        sent=[];client=ShowClient(port=18765)
        client._socket=Mock(sendall=lambda value:sent.append(value))
        client.send_animation('Wave',False);client.send_control('idle')
        self.assertEqual(sent,[b'{"command":"animate","animation":"Wave","repeat":false}\n',b'{"command":"idle"}\n'])
    def test_no_connection_means_no_command_is_sent(self):
        client=ShowClient(port=18765)
        with self.assertRaises(ConnectionError):client.send_animation('Wave',False)


class ComparisonProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('tcp_comparison_probe',ROOT/'diagnosticar_ponte_tcp.py')
        cls.probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.probe)
    def test_occupied_port_does_not_start_godot_or_advance_to_tiktok(self):
        module=self.probe
        endpoint=Mock();endpoint.bind.side_effect=OSError(10048,'test port occupied')
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),\
             patch.object(module,'port_information',return_value={}),\
             patch.object(module,'project_instances',return_value={}),\
             patch.object(module.socket,'socket',return_value=endpoint),\
             patch.object(module.subprocess,'Popen') as spawn,\
             patch.object(module,'offline_tiktok_states') as tiktok:
            report,path=module.run('work')
            self.assertFalse(report['bridge_passed']);self.assertTrue(path.is_file())
            spawn.assert_not_called();tiktok.assert_not_called()
            self.assertEqual(report['tiktok_tests']['result'],'NOT_RUN')
    def test_offline_reader_fixture_cannot_open_network_connections(self):
        # This is only a unit fixture, not approval of the real bridge/reader.
        with patch('socket.create_connection',side_effect=AssertionError('Unit fixture must remain offline')):
            result=self.probe.offline_tiktok_states()
        self.assertEqual(result['result'],'PASS')
        self.assertTrue(result['simulation'])
        self.assertEqual(result['real_tiktok_connections'],0)
        self.assertEqual([row['attempts'] for row in result['transport_cases']],[4,1,1])

    def test_presentation_initialization_enables_status_before_waiting(self):
        client=Mock()
        state={'animation':'Idle'}
        def status_after_command(*args,**kwargs):
            client.send_presentation.assert_called_once_with(walking=False,live=False)
            return state
        with patch.object(self.probe,'wait_status',side_effect=status_after_command):
            self.assertEqual(self.probe.initialize_presentation(client),state)

    def test_existing_godot_listener_is_identified_before_bind_or_spawn(self):
        module=self.probe
        listener={'local_address':'127.0.0.1:18765','state':'LISTENING',
                  'owner':{'pid':10376,'parent_pid':7680,'name':'Godot_v3.6-stable_win64.exe','role':'godot'}}
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),\
             patch.object(module,'port_information',return_value={'connections':{'matching_rows':['  TCP    127.0.0.1:18765        0.0.0.0:0              LISTENING       10376']}}),\
             patch.object(module,'project_instances',return_value={'observed':[{'pid':10376,'parent_pid':7680,'name':'Godot_v3.6-stable_win64.exe','role':'godot'}]}),\
             patch.object(module,'resolve_listener',return_value=listener),\
             patch.object(module.socket,'socket') as create_socket,\
             patch.object(module.subprocess,'Popen') as spawn:
            report,path=module.run('usuario')
            self.assertTrue(path.is_file());self.assertEqual(report['failure']['operation'],'bind_skipped')
            self.assertEqual(report['failure']['listeners'][0]['owner']['pid'],10376)
            create_socket.assert_not_called();spawn.assert_not_called()
            self.assertEqual(report['tiktok_tests']['result'],'NOT_RUN')


if __name__=='__main__':unittest.main()
