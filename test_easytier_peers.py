import json
import unittest
from unittest.mock import patch
from plugins import lan_bridge as bridge


class PeerTests(unittest.TestCase):
    def test_parse_devices(self):
        rows = [{'hostname': '我的电脑', 'ipv4': '10.0.0.1', 'cost': 'Local', 'lat_ms': '-'},
                {'hostname': '好友', 'cidr': '10.0.0.2/24', 'cost': 'p2p', 'lat_ms': '12.30'},
                {'hostname': '远端', 'cost': 'relay(2)', 'lat_ms': '33.00'}]
        parsed = bridge._parse_network_devices(json.dumps(rows))
        self.assertEqual(['本机', '直连', '中转'], [r[2] for r in parsed])
        self.assertEqual('我的电脑', parsed[0][0])
        self.assertEqual('未分配', parsed[2][1])

    def test_reject_ambiguous_or_malformed_data(self):
        for text in ('not json', '{}', '[{"result": []}]'):
            with self.assertRaises(ValueError):
                bridge._parse_network_devices(text)

    def test_query_owned_session_and_failure(self):
        session = {'token': 'old', 'rpc': '127.0.0.1:23456', 'cli': 'easytier-cli'}
        with patch.object(bridge, '_is_running', return_value=True), patch('os.path.isfile', return_value=True), patch.object(bridge, '_run', return_value=(True, '[]')) as run:
            result = bridge.read_network_devices(session)
            self.assertEqual('old', result['token'])
            self.assertIn('查询成功', result['message'])
            self.assertEqual(['easytier-cli', '--rpc-portal', session['rpc'], '-o', 'json', 'peer', 'list'], run.call_args.args[0])
            run.return_value = (False, 'secret error details')
            result = bridge.read_network_devices(session)
            self.assertIn('立即刷新', result['message'])
            self.assertNotIn('secret', result['message'])


if __name__ == '__main__':
    unittest.main()
