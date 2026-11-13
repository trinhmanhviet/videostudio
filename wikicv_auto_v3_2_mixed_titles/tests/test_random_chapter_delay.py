import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crawl_wikicv as crawler


class ChapterDelayTests(unittest.TestCase):
    def test_exact_bounds(self):
        args = SimpleNamespace(delay=2.198347, delay_max=3.982344)
        with patch.object(crawler.random, "uniform", return_value=2.555555) as draw, \
             patch.object(crawler.time, "sleep") as sleep:
            value = crawler.sleep_between_chapters(args)
        draw.assert_called_once_with(2.198347, 3.982344)
        sleep.assert_called_once_with(2.555555)
        self.assertEqual(value, 2.555555)

    def test_invalid_bounds(self):
        with self.assertRaises(ValueError):
            crawler.sleep_between_chapters(SimpleNamespace(delay=4, delay_max=2))


if __name__ == "__main__":
    unittest.main()
