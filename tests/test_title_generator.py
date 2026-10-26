import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import requests
import title_generator as generator


class ChatCompletionTests(unittest.TestCase):
    @patch('title_generator.requests.post')
    def test_uses_configured_endpoint_and_extracts_response(self, post):
        post.return_value.json.return_value = {
            'choices': [{'message': {'content': '# Mountain', 'reasoning_content': 'Notes'}}]
        }
        self.assertEqual(generator.chat_completion('http://example.test/v1/chat/completions', {}, {}),
                         ('# Mountain', 'Notes'))
        post.assert_called_once_with('http://example.test/v1/chat/completions',
                                     json={}, headers={}, timeout=300)

    @patch('title_generator.requests.post')
    def test_http_errors_include_server_response(self, post):
        post.return_value = Mock(ok=False, status_code=400, reason='Bad Request', text='Invalid model')
        with self.assertRaisesRegex(requests.HTTPError, 'Invalid model'):
            generator.chat_completion('http://example.test', {}, {})


class TitleGenerationTests(unittest.TestCase):
    def generate(self, responses, existing=(), max_retries=5):
        with patch('title_generator.encode_image', return_value='encoded'), \
             patch('title_generator.chat_completion', side_effect=responses) as chat, \
             patch('title_generator.time.sleep'):
            result = generator.get_new_name_from_model(
                'image.png', 'Name the image', '.png', set(existing),
                api_url='http://example.test', model_name='vision-model',
                max_retries=max_retries, report=Mock(),
            )
            self.assertEqual(chat.call_args.args[0], 'http://example.test')
            self.assertEqual(chat.call_args.args[1]['model'], 'vision-model')
            return result, chat

    def test_uses_reasoning_when_content_is_empty(self):
        result, _ = self.generate([('', '# Mountain')])
        self.assertEqual(result, 'Mountain')

    def test_requests_alternative_for_sanitized_duplicate(self):
        result, chat = self.generate([('# Mountain: Lake', ''), ('# Forest', '')],
                                     existing={'mountain_ lake.png'})
        self.assertEqual(result, 'Forest')
        self.assertEqual(chat.call_count, 2)
        self.assertIn('already exists', chat.call_args.args[1]['messages'][-1]['content'])

    def test_stops_at_retry_limit(self):
        result, chat = self.generate([('# Mountain', '')] * 2,
                                     existing={'mountain.png'}, max_retries=2)
        self.assertIsNone(result)
        self.assertEqual(chat.call_count, 2)

    def test_returns_none_without_title(self):
        result, chat = self.generate([('No heading', '')])
        self.assertIsNone(result)
        self.assertEqual(chat.call_count, 1)
