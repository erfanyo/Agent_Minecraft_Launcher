import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from plugins import lan_bridge as lan


class TerracottaNodeTests(unittest.TestCase):
    def test_host_and_guest_pass_same_default_nodes(self):
        with patch.object(lan, '_terracotta_request') as request:
            lan.terracotta_host('host')
            host_nodes = request.call_args.args[1]['public_nodes']
            lan.terracotta_join('test-code', 'guest')
            self.assertEqual(request.call_args.args[1]['public_nodes'], host_nodes)
            self.assertEqual(host_nodes, list(lan.TERRACOTTA_PUBLIC_NODES))

    def test_original_nodes_option_does_not_add_presets(self):
        with patch.object(lan, '_terracotta_request') as request:
            lan.terracotta_host('host', [])
            self.assertEqual(request.call_args.args[1]['public_nodes'], [])

    def test_ipc_encodes_repeated_public_node_parameters(self):
        response = Mock()
        response.read.return_value = b''
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(lan, '_terracotta_port', 12345), \
                patch('urllib.request.urlopen', return_value=response) as open_url:
            lan.terracotta_host('host')
            query = parse_qs(urlsplit(open_url.call_args.args[0]).query)
            self.assertEqual(query['public_nodes'], list(lan.TERRACOTTA_PUBLIC_NODES))
            self.assertEqual(query['player'], ['host'])


if __name__ == '__main__':
    unittest.main()
