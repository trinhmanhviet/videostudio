"""Biên tập truyện convert để đọc thành tiếng: gửi từng chương của truyen_gop.txt cho ChatGPT (qua Chrome riêng).

Cách dùng (chạy trong thư mục app):
  python scripts/edit_story.py "<thư mục truyện>"              biên tập mọi chương còn thiếu
  python scripts/edit_story.py "<thư mục truyện>" --tu 1 --den 5

Kết quả: <thư mục truyện>/truyen_gop_bien_tap.txt và thư mục bien_tap/ (từng chương, hồ sơ, tiến độ).
Chạy lại lệnh sẽ tiếp tục từ chương chưa xong; chương đã gửi không bị gửi lại.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
from videostudio.story_editor import StoryEditor  # noqa: E402

parser = argparse.ArgumentParser(description='Biên tập truyện gộp từng chương qua ChatGPT')
parser.add_argument('story', help='thư mục truyện chứa truyen_gop.txt')
parser.add_argument('--tu', type=int, default=None, help='từ chương')
parser.add_argument('--den', type=int, default=None, help='đến chương')
args = parser.parse_args()
summary = StoryEditor(args.story).run(args.tu, args.den)
print(summary['file'])
