"""The prop/fx sheet importer feeds catalog/library.json, which the HyperFrames engine reads."""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.import_meme_library import main as import_library


class ImportLibraryTests(unittest.TestCase):
    def test_sheet_is_cut_into_named_props(self):
        with tempfile.TemporaryDirectory() as folder:
            pack = Path(folder)
            (pack / 'new').mkdir()
            sheet = Image.new('RGB', (900, 1400), (255, 0, 255))
            draw = ImageDraw.Draw(sheet)
            for i in range(8):
                x, y = 80 + (i % 2) * 450, 80 + (i // 2) * 330
                draw.ellipse([x, y, x + 250, y + 200], fill=(250, 250, 250), outline=(0, 0, 0), width=8)
            sheet.save(pack / 'new' / 'prop_food.png')
            import_library(pack)
            items = json.loads((pack / 'catalog' / 'library.json').read_text(encoding='utf-8'))['items']
            kinds = {item['id']: item['kind'] for item in items}
            self.assertEqual(kinds.get('bubble_tea'), 'prop')
            self.assertIn('noodles', kinds)
            for item in items:
                self.assertTrue((pack / 'catalog' / item['file']).is_file(), item['id'])


if __name__ == '__main__':
    unittest.main()
