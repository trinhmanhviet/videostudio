"""Crawl full text posts from a Facebook Page via CDP in the dedicated Chrome browser.
Resumes from existing saved posts and continues scrolling until the true end of the timeline.

Usage:
  python -u scripts/crawl_facebook_page.py
  python -u scripts/crawl_facebook_page.py --max-scrolls 2000
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from videostudio.cdp_protocol import CDPConnection

DEFAULT_URL = "https://www.facebook.com/profile.php?id=61580506574495"
DEFAULT_OUTPUT = ROOT.parent / "data" / "facebook_cases" / "dem-nay-lai-co-chuyen"


def clean_text(text):
    text = re.sub(r'[\u034f\u200b\u200c\u200d\u200e\u200f\ufeff]', '', text)
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'\s*(See more|Xem thêm|See less|Thu gọn)\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'Hồ sơ khép lại, nhưng câu chuyện thì vẫn còn đó[\s\S]*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(#[\w_]+\s*)+$', '', text).strip()
    return text.strip()


def to_filename(title, index):
    s = unicodedata.normalize('NFD', title)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('đ', 'd').replace('Đ', 'd')
    s = re.sub(r'[^a-zA-Z0-9\s_-]', '', s).strip().lower()
    slug = re.sub(r'[\s_]+', '-', s)[:50].strip('-')
    return f"{index:03d}_{slug or 'case'}.md"


async def tick(cdp):
    """Keep background Chrome window compositor awake and rendering via tiny 8x8 screenshot."""
    try:
        await cdp.command('Page.captureScreenshot', {
            'format': 'jpeg', 'quality': 5,
            'clip': {'x': 0, 'y': 0, 'width': 8, 'height': 8, 'scale': 1}
        }, timeout=10)
    except Exception:
        pass


def load_existing_posts(output_dir):
    """Load previously saved posts so we resume seamlessly without duplicates."""
    collected = {}
    collected_meta = []
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return collected, collected_meta, 0

    max_idx = 0
    md_files = sorted(output_dir.glob('*.md'), key=lambda p: p.name)
    for p in md_files:
        if p.name == 'README.md':
            continue
        try:
            m = re.match(r'^(\d+)_', p.name)
            idx_num = int(m.group(1)) if m else 0
            if idx_num > max_idx:
                max_idx = idx_num

            content = p.read_text(encoding='utf-8')
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            if lines and lines[0].startswith('# '):
                title = lines[0][2:].strip()
                collected[title] = content
                words = len(content.split())
                chars = len(content)
                collected_meta.append((title, p.name, words, chars))
        except Exception:
            pass
    return collected, collected_meta, max_idx


def save_single_post(output_dir, index, title, content, target_url):
    output_dir = Path(output_dir)
    fname = to_filename(title, index)
    fpath = output_dir / fname
    words = len(content.split())
    chars = len(content)

    md_content = f"# {title}\n\n"
    md_content += f"> **Nguồn**: Facebook Page ID {target_url.split('id=')[-1] if 'id=' in target_url else target_url}\n"
    md_content += f"> **Độ dài**: {words:,} từ | {chars:,} ký tự\n\n"
    md_content += f"---\n\n"
    md_content += content + "\n"

    fpath.write_text(md_content, encoding='utf-8')
    return fname, words, chars


def update_indexes(collected_meta, output_dir, target_url):
    output_dir = Path(output_dir)
    summary_lines = [
        f"# KỊCH BẢN THÔ CÁC VỤ ÁN - FACEBOOK PAGE",
        f"- **Nguồn**: {target_url}",
        f"- **Thời gian cập nhật**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Tổng số bài viết**: {len(collected_meta)}\n",
        f"## Danh mục bài viết:\n"
    ]

    for idx, (title, fname, words, chars) in enumerate(collected_meta, 1):
        summary_lines.append(f"{idx}. [{title}](./{fname}) — *{words:,} từ / {chars:,} ký tự*")

    (output_dir / "README.md").write_text('\n'.join(summary_lines), encoding='utf-8')


async def crawl(target_url, output_dir, max_scrolls=2500, port=19223):
    print(f"[*] Connecting to Chrome on port {port}...")
    try:
        tabs = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list').read())
    except Exception as e:
        print(f"[!] Cannot connect to Chrome debug port {port}: {e}")
        return

    fb_tab = next((t for t in tabs if t.get('type') == 'page' and 'facebook.com' in t.get('url', '')), None)
    if not fb_tab:
        print(f"[*] Opening new tab for {target_url}...")
        req = urllib.request.urlopen(f'http://127.0.0.1:{port}/json/new?{target_url}')
        fb_tab = json.loads(req.read())
        await asyncio.sleep(4.0)

    ws_url = fb_tab['webSocketDebuggerUrl']
    cdp = CDPConnection()
    await cdp.connect(ws_url)
    print(f"[*] CDP connected to tab: {fb_tab.get('title')}")

    try:
        try:
            await cdp.command('Target.activateTarget', {'targetId': fb_tab['id']})
        except Exception:
            pass

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Load existing progress
        existing, collected_meta, max_idx = load_existing_posts(output_dir)
        print(f"[*] Đã tải {len(existing)} bài viết đã cào trước đó từ đĩa (Max index: {max_idx}). Tiếp tục cào phần còn lại...")
        
        collected_titles = set(existing.keys())
        curr_idx = max_idx

        combined_path = output_dir / "all_cases_combined.txt"
        combined_file = combined_path.open('a', encoding='utf-8')

        no_new_turns = 0
        total_added = 0

        print(f"[*] Bắt đầu cuộn sâu (tối đa {max_scrolls} lượt, tick render liên tục)...")

        for scroll_i in range(1, max_scrolls + 1):
            # 1. Force paint tick
            await tick(cdp)

            # 2. Expand all visible "See more" / "Xem thêm" buttons
            click_expr = """(() => {
                const btns = [...document.querySelectorAll('div[role="button"], span[role="button"]')].filter(b => {
                    const t = (b.innerText || b.textContent || '').trim();
                    return /^(See more|Xem thêm)$/i.test(t) || t.endsWith('See more') || t.endsWith('Xem thêm');
                });
                let count = 0;
                for (const b of btns) {
                    try { b.click(); count++; } catch(e) {}
                }
                return count;
            })()"""
            click_res = await cdp.command('Runtime.evaluate', {'expression': click_expr, 'returnByValue': True})
            clicked = click_res.get('result', {}).get('value', 0)
            if clicked > 0:
                await tick(cdp)
                await asyncio.sleep(0.8)

            # 3. Extract messages currently in DOM
            extract_expr = """(() => {
                const msgs = [...document.querySelectorAll('[data-ad-preview="message"]')];
                return JSON.stringify(msgs.map(m => m.innerText.trim()));
            })()"""
            ext_res = await cdp.command('Runtime.evaluate', {'expression': extract_expr, 'returnByValue': True})
            raw_json = ext_res.get('result', {}).get('value', '[]')
            try:
                posts = json.loads(raw_json)
            except Exception:
                posts = []

            turn_added = 0
            for raw_post in posts:
                cleaned = clean_text(raw_post)
                if len(cleaned) < 150:
                    continue
                # If post looks truncated, wait for next tick to click and expand it
                if len(cleaned) < 600 and ('See more' in raw_post or 'Xem thêm' in raw_post or raw_post.rstrip().endswith('…')):
                    continue

                first_line = cleaned.split('\n')[0].strip()
                if first_line not in collected_titles:
                    collected_titles.add(first_line)
                    turn_added += 1
                    total_added += 1
                    curr_idx += 1
                    
                    fname, words, chars = save_single_post(output_dir, curr_idx, first_line, cleaned, target_url)
                    collected_meta.append((first_line, fname, words, chars))
                    
                    combined_file.write(f"===================================================\n")
                    combined_file.write(f"VỤ ÁN {curr_idx}: {first_line}\n")
                    combined_file.write(f"===================================================\n\n")
                    combined_file.write(cleaned + "\n\n\n")
                    combined_file.flush()

                    print(f"  [+] Bài #{curr_idx:03d} (Lượt {scroll_i}): '{first_line[:55]}' ({chars:,} ký tự)")

            if turn_added > 0:
                no_new_turns = 0
                update_indexes(collected_meta, output_dir, target_url)
            else:
                no_new_turns += 1

            # 4. Deep scroll & jiggle to trigger Facebook's infinite scroll sentinel
            if no_new_turns > 15:
                await cdp.command('Runtime.evaluate', {
                    'expression': 'window.scrollBy(0, -1200);',
                    'returnByValue': True
                })
                await tick(cdp)
                await asyncio.sleep(0.8)
                await cdp.command('Runtime.evaluate', {
                    'expression': '''(() => {
                        const el = document.scrollingElement || document.documentElement;
                        window.scrollTo(0, el.scrollHeight);
                        const spinner = document.querySelector('[role="progressbar"], [data-visualcompletion="loading-state"]');
                        if (spinner) spinner.scrollIntoView();
                    })()''',
                    'returnByValue': True
                })
            elif no_new_turns > 3:
                await cdp.command('Runtime.evaluate', {
                    'expression': 'window.scrollBy(0, -500);',
                    'returnByValue': True
                })
                await tick(cdp)
                await asyncio.sleep(0.4)
                await cdp.command('Runtime.evaluate', {
                    'expression': 'window.scrollTo(0, document.documentElement.scrollHeight);',
                    'returnByValue': True
                })
            else:
                await cdp.command('Runtime.evaluate', {
                    'expression': 'window.scrollTo(0, document.documentElement.scrollHeight);',
                    'returnByValue': True
                })
            await tick(cdp)
            await asyncio.sleep(2.0)

            # 5. Check if at true bottom
            bottom_expr = """(() => {
                const el = document.scrollingElement || document.documentElement;
                return {
                    isBottom: (window.innerHeight + window.scrollY >= el.scrollHeight - 60),
                    scrollY: Math.round(window.scrollY),
                    scrollHeight: el.scrollHeight
                };
            })()"""
            bottom_res = await cdp.command('Runtime.evaluate', {'expression': bottom_expr, 'returnByValue': True})
            state = bottom_res.get('result', {}).get('value', {})
            is_bottom = state.get('isBottom', False)

            # Log periodic status every 20 scrolls
            if scroll_i % 20 == 0:
                print(f"--- [Tiến độ: Lượt {scroll_i}/{max_scrolls}] Tổng bài: {len(collected_titles)} (Thêm mới: +{total_added}) | Y: {state.get('scrollY'):,} / {state.get('scrollHeight'):,} px ---")

            # Only stop if we've been stuck at true bottom for 80 consecutive attempts (~160-200s with nothing loading)
            if is_bottom and no_new_turns >= 80:
                print(f"[*] Đã cuộn và tick 80 lần liên tục tại đáy trang ({state.get('scrollHeight'):,} px) không có bài mới. Kết thúc cào.")
                break

            if no_new_turns >= 120:
                print(f"[*] Không còn bài viết mới sau 120 lượt cuộn liên tiếp. Kết thúc cào.")
                break

        combined_file.close()
        update_indexes(collected_meta, output_dir, target_url)
        print(f"\n[+] HOÀN TẤT TOÀN BỘ! Tổng cộng: {len(collected_titles)} bài viết vụ án (Thêm mới đợt này: {total_added}).")
        print(f"[+] Thư mục: {output_dir}")

    finally:
        await cdp.close()


def main():
    parser = argparse.ArgumentParser(description="Crawl Facebook Page Posts via CDP")
    parser.add_argument("--url", default=DEFAULT_URL, help="Facebook page URL")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="Output directory")
    parser.add_argument("--max-scrolls", type=int, default=1500, help="Max scrolls")
    args = parser.parse_args()

    asyncio.run(crawl(args.url, args.out, max_scrolls=args.max_scrolls))


if __name__ == '__main__':
    main()
