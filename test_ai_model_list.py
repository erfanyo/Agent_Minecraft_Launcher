import unittest
from unittest.mock import Mock, patch
from ai_model_list import fetch_models


class ModelListTests(unittest.TestCase):
    def test_models_and_auth(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': [{'id': 'glm-4.7-flash'}, {'id': 'glm-4.7-flash'}, {'id': 'another'}]}
        with patch('ai_model_list.requests.get', return_value=response) as get:
            self.assertEqual(fetch_models('https://example.com/v4/', 'fake'), ['another', 'glm-4.7-flash'])
        self.assertEqual(get.call_args.args[0], 'https://example.com/v4/models')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer fake')

    def test_unsupported_and_errors(self):
        for status in (401, 403, 404, 405, 429, 302, 500):
            with patch('ai_model_list.requests.get', return_value=Mock(status_code=status)):
                with self.assertRaises(ValueError):
                    fetch_models('https://example.com/v1')

    def test_no_remote_plaintext_key(self):
        with self.assertRaises(ValueError):
            fetch_models('http://example.com/v1', 'fake')

    def test_empty_list(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': []}
        with patch('ai_model_list.requests.get', return_value=response):
            with self.assertRaises(ValueError):
                fetch_models('https://example.com/v1')
