"""Exhaustive, resilient crawler for Facebook page 'Sử ta và họ'.
Resumes from existing posts, continues scrolling down smoothly through the feed,
expands all 'See more' buttons, and captures every single post until the absolute end of the timeline.
"""
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

OUTPUT_DIR = ROOT.parent / "data" / "facebook_cases" / "su-ta-va-ho" / "raw_md"


def clean_text(text):
    text = re.sub(r'[\u034f\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]', '', text)
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'\s*(See more|Xem thêm|See less|Thu gọn)\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'(#[\w_]+\s*)+$', '', text).strip()
    return text.strip()


def to_filename(title, index):
    s = unicodedata.normalize('NFD', title)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('đ', 'd').replace('Đ', 'd').replace('ß', 'ss')
    s = re.sub(r'[^a-zA-Z0-9\s_-]', '', s).strip().lower()
    slug = re.sub(r'[\s_]+', '-', s)[:50].strip('-')
    return f"{index:03d}_{slug or 'bai-viet'}.md"


async def tick(cdp):
    """Keep Chrome compositor awake and active."""
    try:
        await cdp.command('Page.captureScreenshot', {
            'format': 'jpeg', 'quality': 5,
            'clip': {'x': 0, 'y': 0, 'width': 8, 'height': 8, 'scale': 1}
        }, timeout=5)
    except Exception:
        pass


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


def update_indexes(posts_ordered, output_dir, target_url):
    output_dir = Path(output_dir)
    summary_lines = [
        f"# KỊCH BẢN THÔ - SỬ TA VÀ HỌ (FACEBOOK PAGE)",
        f"- **Nguồn**: {target_url}",
        f"- **Thời gian cập nhật**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Tổng số bài viết**: {len(posts_ordered)}\n",
        f"## Danh mục bài viết:\n"
    ]

    combined_lines = []
    for idx, p in enumerate(posts_ordered, 1):
        summary_lines.append(f"{idx}. [{p['title']}](./{p['fname']}) — *{p['words']:,} từ / {p['chars']:,} ký tự*")
        divider = "=" * 60
        combined_lines.append(divider)
        combined_lines.append(f"BÀI VIẾT #{idx:03d}: {p['title']}")
        combined_lines.append(divider + "\n")
        combined_lines.append(p['content'])
        combined_lines.append("\n\n")

    (output_dir / "README.md").write_text('\n'.join(summary_lines), encoding='utf-8')
    (output_dir / "all_cases_combined.txt").write_text('\n'.join(combined_lines), encoding='utf-8')


def load_existing_posts(output_dir):
    """Load already saved posts so we resume seamlessly without re-scraping from top."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_files = sorted(output_dir.glob('*.md'), key=lambda p: p.name)
    existing_files = [f for f in existing_files if f.name != 'README.md']

    collected = {}
    posts_ordered = []

    for f in existing_files:
        m = re.match(r'^(\d+)_', f.name)
        if not m:
            continue
        idx = int(m.group(1))
        text = f.read_text(encoding='utf-8')
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            continue

        title = lines[0][2:].strip() if lines[0].startswith('# ') else lines[0]
        body_idx = -1
        for i, l in enumerate(lines):
            if l == '---':
                body_idx = i + 1
                break
        body = '\n'.join(lines[body_idx:]).strip() if body_idx != -1 else text

        norm_key = re.sub(r'[\W_]+', '', unicodedata.normalize('NFD', title).lower())
        p_info = {
            'idx': idx,
            'title': title,
            'fname': f.name,
            'words': len(body.split()),
            'chars': len(body),
            'content': body
        }
        collected[norm_key] = p_info
        posts_ordered.append(p_info)

    posts_ordered.sort(key=lambda x: x['idx'])
    return collected, posts_ordered


async def crawl(max_scrolls=15000, port=19223):
    print(f"[*] Kết nối tới Chrome trên cổng {port}...", flush=True)
    try:
        tabs = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list').read())
    except Exception as e:
        print(f"[!] Không thể kết nối tới Chrome cổng {port}: {e}", flush=True)
        return

    fb_tab = next((t for t in tabs if t.get('type') == 'page' and 'facebook.com' in t.get('url', '')), None)
    if not fb_tab:
        print(f"[!] Không tìm thấy tab Facebook đang mở trong Chrome!", flush=True)
        return

    target_url = fb_tab.get('url', 'https://www.facebook.com/profile.php?id=61583850062328')
    cdp = CDPConnection()
    await cdp.connect(fb_tab['webSocketDebuggerUrl'])
    print(f"[*] CDP đã kết nối vào tab: '{fb_tab.get('title')}' ({target_url})", flush=True)

    try:
        try:
            await cdp.command('Target.activateTarget', {'targetId': fb_tab['id']})
        except Exception:
            pass

        collected, posts_ordered = load_existing_posts(OUTPUT_DIR)
        print(f"[*] Đã tải trước {len(posts_ordered)} bài viết đã có sẵn trong kho.", flush=True)

        no_new_turns = 0
        last_scroll_height = 0
        same_height_count = 0

        print(f"[*] Bắt đầu quét liên tục cho tới khi cào bằng sạch toàn bộ timeline...", flush=True)

        for scroll_i in range(1, max_scrolls + 1):
            # 1. Expand all 'See more' / 'Xem thêm' in view
            click_expr = """(() => {
                const btns = [...document.querySelectorAll('div[role="button"], span[role="button"]')].filter(b => {
                    const t = (b.innerText || '').trim();
                    return t === 'See more' || t === 'Xem thêm';
                });
                let c = 0;
                for (const b of btns) {
                    try { b.click(); c++; } catch(e) {}
                }
                return c;
            })()"""
            click_res = await cdp.command('Runtime.evaluate', {'expression': click_expr, 'returnByValue': True})
            clicked = click_res.get('result', {}).get('value', 0)
            if clicked > 0:
                await asyncio.sleep(0.4)

            # Check if there is a 'Retry' / 'Thử lại' button
            retry_expr = """(() => {
                const retryBtn = [...document.querySelectorAll('div[role="button"], span[role="button"], button')].find(b => {
                    const t = (b.innerText || '').trim();
                    return t === 'Retry' || t === 'Thử lại' || t === 'Tải lại';
                });
                if (retryBtn) { retryBtn.click(); return true; }
                return false;
            })()"""
            await cdp.command('Runtime.evaluate', {'expression': retry_expr})

            # 2. Extract all posts in DOM
            extract_expr = """(() => {
                const msgs = [...document.querySelectorAll('[data-ad-preview="message"]')];
                return msgs.map(m => {
                    const hasSeeMore = !![...m.querySelectorAll('*')].find(el => {
                        const t = (el.innerText || '').trim();
                        return t === 'See more' || t === 'Xem thêm';
                    });
                    return {
                        text: m.innerText || '',
                        hasSeeMore: hasSeeMore
                    };
                });
            })()"""
            ext_res = await cdp.command('Runtime.evaluate', {'expression': extract_expr, 'returnByValue': True})
            dom_posts = ext_res.get('result', {}).get('value', [])

            turn_added = 0
            for item in dom_posts:
                raw_text = item.get('text', '')
                has_see_more = item.get('hasSeeMore', False)
                cleaned = clean_text(raw_text)

                if len(cleaned) < 40:
                    continue

                if has_see_more and len(cleaned) < 500:
                    continue

                lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
                if not lines:
                    continue
                first_line = lines[0]
                norm_key = re.sub(r'[\W_]+', '', unicodedata.normalize('NFD', first_line).lower())

                if norm_key not in collected:
                    turn_added += 1
                    curr_idx = len(posts_ordered) + 1
                    fname, words, chars = save_single_post(OUTPUT_DIR, curr_idx, first_line, cleaned, target_url)
                    p_info = {
                        'idx': curr_idx,
                        'title': first_line,
                        'fname': fname,
                        'words': words,
                        'chars': chars,
                        'content': cleaned
                    }
                    collected[norm_key] = p_info
                    posts_ordered.append(p_info)
                    print(f"  [+] #{curr_idx:03d} (Bước {scroll_i}): '{first_line[:55]}' ({chars:,} ký tự / {words:,} từ)", flush=True)
                else:
                    existing = collected[norm_key]
                    if len(cleaned) > existing['chars'] + 50:
                        fname, words, chars = save_single_post(OUTPUT_DIR, existing['idx'], first_line, cleaned, target_url)
                        existing['words'] = words
                        existing['chars'] = chars
                        existing['content'] = cleaned
                        print(f"  [*] Cập nhật mở rộng #{existing['idx']:03d}: '{first_line[:45]}' -> {chars:,} ký tự", flush=True)

            if turn_added > 0:
                no_new_turns = 0
                update_indexes(posts_ordered, OUTPUT_DIR, target_url)
            else:
                no_new_turns += 1

            # 3. Check scroll state and bottom sentinel
            check_state_expr = """(() => {
                const doc = document.scrollingElement || document.documentElement;
                const scrollY = Math.round(window.scrollY);
                const scrollHeight = doc.scrollHeight;
                const innerHeight = window.innerHeight;
                const isBottom = (scrollY + innerHeight >= scrollHeight - 350);
                const spinners = document.querySelectorAll('[role="progressbar"], [data-visualcompletion="loading-state"]').length;
                const text = document.body ? document.body.innerText : '';
                const endReached = text.includes('Không còn bài viết nào nữa') || text.includes('End of results') || text.includes('Đã xem hết tất cả bài viết');
                return { scrollY, scrollHeight, innerHeight, isBottom, spinners, endReached };
            })()"""
            st_res = await cdp.command('Runtime.evaluate', {'expression': check_state_expr, 'returnByValue': True})
            st = st_res.get('result', {}).get('value', {})
            cur_scroll_height = st.get('scrollHeight', 0)
            is_bottom = st.get('isBottom', False)
            spinners = st.get('spinners', 0)
            end_reached = st.get('endReached', False)

            if cur_scroll_height == last_scroll_height:
                same_height_count += 1
            else:
                same_height_count = 0
                last_scroll_height = cur_scroll_height

            # 4. Smart advancing
            if is_bottom:
                # Dispatch wheel event downwards
                try:
                    await cdp.command('Input.dispatchMouseEvent', {
                        'type': 'mouseWheel', 'x': 500, 'y': 500, 'deltaX': 0, 'deltaY': 800
                    })
                except Exception:
                    pass

                # Dispatch PageDown key
                await cdp.command('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'PageDown', 'code': 'PageDown'})
                await cdp.command('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'PageDown', 'code': 'PageDown'})
                await asyncio.sleep(0.3)
                await tick(cdp)

                # Big jiggle: scroll back up 2,000px so IntersectionObserver completely exits the rootMargin (usually 1000px)
                await cdp.command('Runtime.evaluate', {'expression': 'window.scrollBy(0, -2000);'})
                await asyncio.sleep(0.4)
                await tick(cdp)
                # Snap back down
                await cdp.command('Runtime.evaluate', {'expression': 'window.scrollTo(0, (document.scrollingElement || document.documentElement).scrollHeight);'})
                await asyncio.sleep(1.5)
            else:
                # Progressive smooth scroll
                await cdp.command('Runtime.evaluate', {'expression': 'window.scrollBy(0, 800);'})
                await asyncio.sleep(0.35)

            await tick(cdp)
            await asyncio.sleep(0.15)

            if scroll_i % 5 == 0 or turn_added > 0:
                print(f"--- [Tiến độ: Lượt {scroll_i}/{max_scrolls}] Tổng bài: {len(posts_ordered)} | Y: {st.get('scrollY', 0):,} / {cur_scroll_height:,} px | Spinners: {spinners} ---", flush=True)

            # Explicit end reached
            if end_reached:
                print(f"[*] Đã gặp thông báo kết thúc dòng thời gian từ Facebook. Hoàn thành cào.", flush=True)
                break

            # Very generous stall threshold: 300 turns of no new posts AND 200 consecutive turns of same height
            if no_new_turns >= 300 and same_height_count >= 200:
                print(f"[*] Không còn bài mới sau {no_new_turns} lượt cuộn liên tiếp tại đáy trang ({cur_scroll_height:,} px). Kết thúc cào.", flush=True)
                break

        update_indexes(posts_ordered, OUTPUT_DIR, target_url)
        print(f"\n[+] HOÀN TẤT CÀO THÔ! Tổng cộng: {len(posts_ordered)} bài viết.", flush=True)
        print(f"[+] Thư mục thô: {OUTPUT_DIR}", flush=True)

    finally:
        await cdp.close()


if __name__ == '__main__':
    asyncio.run(crawl())
