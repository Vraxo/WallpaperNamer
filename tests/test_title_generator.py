import base64
import io
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import requests
from PIL import Image as PILImage
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


class TransientErrorTests(unittest.TestCase):
    def generate(self, responses, max_retries=5):
        with patch('title_generator.encode_image', return_value='encoded'), \
             patch('title_generator.chat_completion', side_effect=responses) as chat, \
             patch('title_generator.time.sleep'):
            return generator.get_new_name_from_model(
                'image.png', 'Name the image', '.png', set(),
                api_url='http://example.test', model_name='vision-model',
                max_retries=max_retries, report=Mock(),
            ), chat

    def _http_error(self, status_code):
        response = Mock(ok=False, status_code=status_code, reason='Error', text='boom')
        return requests.HTTPError(f'HTTP {status_code}', response=response)

    def test_retries_on_connection_error_then_succeeds(self):
        result, chat = self.generate([
            ConnectionError("Remote end closed connection without response"),
            ('# Mountain', ''),
        ])
        self.assertEqual(result, 'Mountain')
        self.assertEqual(chat.call_count, 2)

    def test_retries_on_http_500_then_succeeds(self):
        result, chat = self.generate([
            self._http_error(500),
            ('# Mountain', ''),
        ])
        self.assertEqual(result, 'Mountain')
        self.assertEqual(chat.call_count, 2)

    def test_retries_on_http_503_then_succeeds(self):
        result, chat = self.generate([
            self._http_error(503),
            self._http_error(503),
            ('# Mountain', ''),
        ])
        self.assertEqual(result, 'Mountain')
        self.assertEqual(chat.call_count, 3)

    def test_does_not_retry_http_400_counts_single_call(self):
        with patch('title_generator.encode_image', return_value='encoded'), \
             patch('title_generator.chat_completion', side_effect=[self._http_error(400)]) as chat, \
             patch('title_generator.time.sleep'):
            with self.assertRaises(requests.HTTPError):
                generator.get_new_name_from_model(
                    'image.png', 'Name the image', '.png', set(),
                    api_url='http://example.test', model_name='vision-model',
                    report=Mock(),
                )
        self.assertEqual(chat.call_count, 1)

    def test_exhausts_transient_retries_and_raises(self):
        with patch('title_generator.encode_image', return_value='encoded'), \
             patch('title_generator.chat_completion',
                    side_effect=[ConnectionError('boom')] * generator.MAX_TRANSIENT_ATTEMPTS), \
             patch('title_generator.time.sleep'):
            with self.assertRaises(ConnectionError):
                generator.get_new_name_from_model(
                    'image.png', 'Name the image', '.png', set(),
                    api_url='http://example.test', model_name='vision-model',
                    report=Mock(),
                )


class ImageEncodingTests(unittest.TestCase):
    def _write_image(self, size, ext='.png', color='red'):
        directory = tempfile.mkdtemp()
        path = Path(directory) / f'image{ext}'
        with PILImage.new('RGB', size, color) as img:
            img.save(path, ext.lstrip('.').upper() if ext != '.png' else 'PNG')
        return path

    def test_within_limit_sent_as_raw_bytes(self):
        path = self._write_image((800, 600))
        expected = base64.b64encode(path.read_bytes()).decode('utf-8')
        self.assertEqual(generator.encode_image(path, '.png'), expected)

    def test_oversized_square_is_resized_to_limit(self):
        path = self._write_image((2000, 2000))
        data = base64.b64decode(generator.encode_image(path, '.png'))
        with PILImage.open(io.BytesIO(data)) as img:
            self.assertEqual(img.size, (1024, 1024))

    def test_oversized_landscape_keeps_aspect_ratio(self):
        path = self._write_image((2000, 1000))
        data = base64.b64decode(generator.encode_image(path, '.png'))
        with PILImage.open(io.BytesIO(data)) as img:
            self.assertEqual(max(img.size), generator.MAX_IMAGE_DIMENSION)
            self.assertEqual(img.size, (1024, 512))

    def test_exact_limit_is_sent_as_raw_bytes(self):
        path = self._write_image((1024, 1024))
        expected = base64.b64encode(path.read_bytes()).decode('utf-8')
        self.assertEqual(generator.encode_image(path, '.png'), expected)

    def test_webp_is_converted_to_png_and_resized(self):
        path = self._write_image((2000, 1000), ext='.webp')
        data = base64.b64decode(generator.encode_image(path, '.webp'))
        with PILImage.open(io.BytesIO(data)) as img:
            self.assertEqual(img.format, 'PNG')
            self.assertEqual(img.size, (1024, 512))
