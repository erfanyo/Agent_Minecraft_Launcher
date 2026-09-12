import unittest
from unittest.mock import patch, Mock
from plugins import lan_bridge as bridge


class IPTests(unittest.TestCase):
    def test_only_virtual_ip_is_accepted(self):
        self.assertEqual('10.0.0.1', bridge._parse_virtual_ip('| Virtual IP | 10.0.0.1/24 |\n| Public IPv4 | 8.8.8.8 |'))
        self.assertEqual('', bridge._parse_virtual_ip('| Public IPv4 | 8.8.8.8 |'))
        self.assertEqual('', bridge._parse_virtual_ip('| Virtual IP | 0.0.0.0 |'))
        self.assertEqual('', bridge._parse_virtual_ip('| Virtual IP | 999.0.0.1 |'))

    def test_query_uses_owned_endpoint(self):
        session = {'token': 'a', 'rpc': '127.0.0.1:23456', 'cli': 'easytier-cli'}
        with patch.object(bridge, '_session', session), patch.object(bridge, '_is_running', return_value=True), patch('os.path.isfile', return_value=True), patch.object(bridge, '_run', return_value=(True, '| Virtual IP | 10.0.0.5 |')) as run:
            result = bridge.read_virtual_ip()
        self.assertEqual('10.0.0.5', result['ip'])
        self.assertIn('未验证', result['message'])
        self.assertIn('127.0.0.1:23456', run.call_args.args[0])

    def test_start_enables_dhcp_and_loopback_rpc(self):
        with patch.object(bridge, '_process', None), patch.object(bridge, '_elevated_pid', None), patch.object(bridge, '_session', None), patch.object(bridge, '_find_core', return_value='/fake/easytier-core'), patch.object(bridge, '_run', return_value=(True, 'v2.6.4')), patch.object(bridge, '_is_admin', return_value=True), patch.object(bridge, '_is_running', side_effect=[False, True]), patch.object(bridge.subprocess, 'Popen') as spawn, patch.object(bridge.time, 'sleep'):
            result = bridge.setup_easytier('room', 'secret')
            args = spawn.call_args.args[0]
            self.assertTrue(result['ok'])
            self.assertEqual('true', args[args.index('--dhcp') + 1])
            self.assertTrue(args[args.index('--rpc-portal') + 1].startswith('127.0.0.1:'))


if __name__ == '__main__':
    unittest.main()
