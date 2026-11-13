import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crawl_wikicv as c

class CombinedTests(unittest.TestCase):
    def test_removes_only_chapter_header_source_line(self):
        data = "Chương 172 còn không có tận hứng\nNguồn: https://wikicv.org/truyen/demo/chuong-172\n\nLương Thiệu Hành...\nNguồn: câu này nằm trong nội dung truyện\n"
        actual = c.text_for_combined(data)
        self.assertEqual(actual, "Chương 172 còn không có tận hứng\n\nLương Thiệu Hành...\nNguồn: câu này nằm trong nội dung truyện")

    def test_unchanged_if_no_source_line(self):
        src="Chương 1\n\nLời kể\n"
        self.assertEqual(c.text_for_combined(src),src.strip())

    def test_rebuild_offline_removes_legacy_sources_from_individual_chapters(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/"du_lieu_truyen"
            folder=base/"story"
            (folder/"chapters").mkdir(parents=True)
            records=[]
            for i in (1,2):
                rel=f"chapters/chuong_{i:05d}.txt"
                text=f"Chương {i}\nNguồn: https://wikicv.org/truyen/demo/ch{i}\n\nNội dung {i}\n"
                (folder/rel).write_text(text,encoding="utf-8")
                records.append({"number":i,"title":f"Chương {i}","url":f"https://wikicv.org/truyen/demo/ch{i}","file":rel,"characters":len(text),"sha256":"none","next_url":None})
            (folder/"chapters.json").write_text(json.dumps(records,ensure_ascii=False),encoding="utf-8")
            (folder/"truyen.json").write_text(json.dumps({"title":"Tên truyện"},ensure_ascii=False),encoding="utf-8")
            self.assertEqual(c.rebuild_combined_offline(base),1)
            merged=(folder/"truyen_gop.txt").read_text(encoding="utf-8")
            self.assertIn("Tên truyện\n\n",merged)
            self.assertIn("Chương 1\n\nNội dung 1",merged)
            self.assertIn("Chương 2\n\nNội dung 2",merged)
            self.assertNotIn("Nguồn:", merged)
            chapter_one=(folder/"chapters/chuong_00001.txt").read_text(encoding="utf-8")
            chapter_two=(folder/"chapters/chuong_00002.txt").read_text(encoding="utf-8")
            self.assertNotIn("Nguồn:", chapter_one)
            self.assertNotIn("Nguồn:", chapter_two)
            metadata=json.loads((folder/"truyen.json").read_text(encoding="utf-8"))
            self.assertEqual([x["url"] for x in metadata["chapter_sources"]], [
                "https://wikicv.org/truyen/demo/ch1", "https://wikicv.org/truyen/demo/ch2"])
            self.assertEqual(metadata["downloaded_chapters"], 2)

if __name__ == "__main__":
    unittest.main()
