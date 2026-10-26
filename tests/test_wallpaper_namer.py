import os
from pathlib import Path
import tempfile
import sys
import unittest

# Make the standalone scripts importable during test discovery.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from title_generator import parse_title
from wallpaper_namer import (
    get_unique_filename,
    load_system_prompt,
    sanitize_filename,
)


class SanitizeFilenameTests(unittest.TestCase):
    def test_replaces_invalid_characters(self):
        self.assertEqual(sanitize_filename('a\\b/c:d*e?f"g<h>i|j'), 'a_b_c_d_e_f_g_h_i_j')

    def test_strips_edge_spaces_and_periods(self):
        self.assertEqual(sanitize_filename(' . Crescent Mountain. '), 'Crescent Mountain')

    def test_preserves_unicode(self):
        self.assertEqual(sanitize_filename('Yö järvellä'), 'Yö järvellä')

    def test_limits_length(self):
        self.assertEqual(sanitize_filename('a' * 201), 'a' * 200)


class ParseTitleTests(unittest.TestCase):
    def test_supported_formats(self):
        cases = [
            ('# Crescent Mountain\n\nDescription.', 'Crescent Mountain'),
            ('  # Crescent Mountain ##  ', 'Crescent Mountain'),
            ('<TITLE> Crescent Mountain </TITLE>', 'Crescent Mountain'),
            ('**"Crescent Mountain"**', 'Crescent Mountain'),
        ]
        for content, expected in cases:
            with self.subTest(content=content):
                self.assertEqual(parse_title(content), expected)

    def test_prefers_heading_over_fallbacks(self):
        self.assertEqual(parse_title('**Other**\n# Mountain'), 'Mountain')

    def test_missing_title(self):
        for content in ('', 'Just a description.', '## Not an H1'):
            with self.subTest(content=content):
                self.assertIsNone(parse_title(content))


class UniqueFilenameTests(unittest.TestCase):
    def test_unused_name_is_unchanged(self):
        self.assertEqual(get_unique_filename(set(), 'Mountain', '.png'), 'Mountain.png')

    def test_collisions_are_case_insensitive(self):
        existing = {'mountain.png', 'mountain_1.png'}
        self.assertEqual(get_unique_filename(existing, 'Mountain', '.png'), 'Mountain_2.png')
        self.assertEqual(existing, {'mountain.png', 'mountain_1.png'})

    def test_different_extension_is_not_a_collision(self):
        self.assertEqual(get_unique_filename({'mountain.jpg'}, 'Mountain', '.png'), 'Mountain.png')


class PromptPathTests(unittest.TestCase):
    def test_loads_default_prompt_from_another_directory(self):
        expected = (Path(__file__).resolve().parents[1] / 'src' / 'prompt.md').read_text(encoding='utf-8')
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(load_system_prompt(), expected)
            finally:
                os.chdir(original_directory)


if __name__ == '__main__':
    unittest.main()
