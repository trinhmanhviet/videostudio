"""Exhaustive, non-spammy Facebook crawler for 'Sử ta và họ'.
- Zero screenshot spamming.
- Smooth, progressive scrolling with automatic 'See more' expansion.
- Recognizes active loading skeletons and waits patiently for GraphQL.
- Only stops when Facebook feed is genuinely exhausted (very generous stall limit: 300+).
- Takes ONE single screenshot at the very end to confirm.
- Synchronizes clean_txt alongside raw_md.
"""
import asyncio
import base64
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
try:
    from scripts.facebook.clean_su_ta_va_ho import process_all as sync_clean_txt
except ImportError:
    try:
        from clean_su_ta_va_ho import process_all as sync_clean_txt
    except ImportError:
        from .clean_su_ta_va_ho import process_all as sync_clean_txt

OUTPUT_DIR = ROOT.parent / "data" / "facebook_cases" / "su-ta-va-ho" / "raw_md"
ARTIFACT_DIR = Path(r"C:\Users\leath\.gemini\antigravity\brain\4b6b401d-b80b-4f61-aaca-864a0e5c7135")


def clean_text(text):
    text = re.sub(r'[\u034f\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]', '', text)
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'\s*(See more|Xem thêm|See less|Thu gọn)\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'(#[\w_]+\s*)+$', '', text).strip()
    return text.strip()


def get_post_key(cleaned):
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    if not lines:
        return ""
    k0 = re.sub(r'[\W_]+', '', unicodedata.normalize('NFD', lines[0]).lower())
    k1 = re.sub(r'[\W_]+', '', unicodedata.normalize('NFD', lines[1]).lower()) if len(lines) > 1 else ""
    if len(lines[0]) < 80 and k1:
        return f"{k0}_{k1[:30]}"
    return k0[:60]


def to_filename(title, index):
    s = unicodedata.normalize('NFD', title)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('đ', 'd').replace('Đ', 'd').replace('ß', 'ss')
    s = re.sub(r'[^a-zA-Z0-9\s_-]', '', s).strip().lower()
    slug = re.sub(r'[\s_]+', '-', s)[:50].strip('-')
    return f"{index:03d}_{slug or 'bai-viet'}.md"


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
    # Also mirror root README
    (ROOT.parent / "data" / "facebook_cases" / "su-ta-va-ho" / "README.md").write_text('\n'.join(summary_lines), encoding='utf-8')


def load_existing_posts(output_dir):
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

        key = get_post_key(body)
        p_info = {
            'idx': idx,
            'title': title,
            'fname': f.name,
            'words': len(body.split()),
            'chars': len(body),
            'content': body
        }
        collected[key] = p_info
        posts_ordered.append(p_info)

    posts_ordered.sort(key=lambda x: x['idx'])
    return collected, posts_ordered


async def crawl(max_scrolls=20000, port=19223):
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
        STALL_LIMIT = 600

        print(f"[*] Bắt đầu quét mượt liên tục (tối đa {max_scrolls} bước cuộn, KHÔNG spam ảnh chụp màn hình)...", flush=True)

        for scroll_i in range(1, max_scrolls + 1):
            # 1. Expand all 'See more' in view
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
                await asyncio.sleep(0.35)

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
                
                key = get_post_key(cleaned)
                title = lines[0]
                if len(lines) > 1 and len(title) < 70 and ('tập' in lines[1].lower() or 'phần' in lines[1].lower() or ':' in lines[1]):
                    full_title = f"{title} - {lines[1]}"
                else:
                    full_title = title

                if key not in collected:
                    turn_added += 1
                    curr_idx = len(posts_ordered) + 1
                    fname, words, chars = save_single_post(OUTPUT_DIR, curr_idx, full_title, cleaned, target_url)
                    p_info = {
                        'idx': curr_idx,
                        'title': full_title,
                        'fname': fname,
                        'words': words,
                        'chars': chars,
                        'content': cleaned
                    }
                    collected[key] = p_info
                    posts_ordered.append(p_info)
                    print(f"  [+] #{curr_idx:03d} (Bước {scroll_i}): '{full_title[:55]}' ({chars:,} ký tự / {words:,} từ)", flush=True)
                else:
                    existing = collected[key]
                    if len(cleaned) > existing['chars'] + 50:
                        fname, words, chars = save_single_post(OUTPUT_DIR, existing['idx'], full_title, cleaned, target_url)
                        existing['words'] = words
                        existing['chars'] = chars
                        existing['content'] = cleaned
                        print(f"  [*] Cập nhật mở rộng #{existing['idx']:03d}: '{full_title[:45]}' -> {chars:,} ký tự", flush=True)

            if turn_added > 0:
                no_new_turns = 0
                update_indexes(posts_ordered, OUTPUT_DIR, target_url)
                try:
                    sync_clean_txt()
                except Exception:
                    pass
            else:
                no_new_turns += 1

            # 3. Check scroll state and bottom sentinel
            check_state_expr = """(() => {
                const doc = document.scrollingElement || document.documentElement;
                const scrollY = Math.round(window.scrollY);
                const scrollHeight = doc.scrollHeight;
                const innerHeight = window.innerHeight;
                const isBottom = (scrollY + innerHeight >= scrollHeight - 600);
                const isActivelyLoading = document.querySelectorAll('[data-visualcompletion="loading-state"]').length > 0;
                const text = document.body ? document.body.innerText : '';
                const endReached = text.includes('Không còn bài viết nào nữa') || text.includes('End of results') || text.includes('Đã xem hết tất cả bài viết');
                return { scrollY, scrollHeight, innerHeight, isBottom, isActivelyLoading, endReached };
            })()"""
            st_res = await cdp.command('Runtime.evaluate', {'expression': check_state_expr, 'returnByValue': True})
            st = st_res.get('result', {}).get('value', {})
            cur_scroll_height = st.get('scrollHeight', 0)
            is_bottom = st.get('isBottom', False)
            is_loading = st.get('isActivelyLoading', False)
            end_reached = st.get('endReached', False)

            if cur_scroll_height == last_scroll_height:
                same_height_count += 1
            else:
                same_height_count = 0
                last_scroll_height = cur_scroll_height

            # 4. Advance
            if is_bottom:
                # Dispatch PageDown
                await cdp.command('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'PageDown', 'code': 'PageDown'})
                await cdp.command('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'PageDown', 'code': 'PageDown'})
                await asyncio.sleep(0.3)

                # Tiered jiggle to unblock throttled GraphQL
                if same_height_count > 150:
                    # Deep jiggle: scroll up 6,000px, wait 8 seconds
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollBy(0, -6000);'})
                    await asyncio.sleep(1.0)
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollTo(0, (document.scrollingElement || document.documentElement).scrollHeight);'})
                    await asyncio.sleep(8.0)
                elif same_height_count > 50:
                    # Medium jiggle: scroll up 3,500px, wait 4.5 seconds
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollBy(0, -3500);'})
                    await asyncio.sleep(0.6)
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollTo(0, (document.scrollingElement || document.documentElement).scrollHeight);'})
                    await asyncio.sleep(4.5)
                elif same_height_count > 15:
                    # Small jiggle: scroll up 2,000px, wait 2.5 seconds
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollBy(0, -2000);'})
                    await asyncio.sleep(0.5)
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollTo(0, (document.scrollingElement || document.documentElement).scrollHeight);'})
                    await asyncio.sleep(2.5)
                else:
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollBy(0, -1500);'})
                    await asyncio.sleep(0.4)
                    await cdp.command('Runtime.evaluate', {'expression': 'window.scrollTo(0, (document.scrollingElement || document.documentElement).scrollHeight);'})
                    await asyncio.sleep(1.8)
            else:
                # Progressive smooth scroll
                await cdp.command('Runtime.evaluate', {'expression': 'window.scrollBy(0, 850);'})
                await asyncio.sleep(0.35)

            if scroll_i % 5 == 0 or turn_added > 0:
                print(f"--- [Tiến độ: Lượt {scroll_i}/{max_scrolls}] Tổng bài: {len(posts_ordered)} | Y: {st.get('scrollY', 0):,} / {cur_scroll_height:,} px | Đang tải: {is_loading} | Stall: {same_height_count} ---", flush=True)

            if end_reached:
                print(f"[*] Đã gặp thông báo kết thúc dòng thời gian từ Facebook. Hoàn thành cào.", flush=True)
                break

            # Resilient stall condition: 600 attempts with multi-tiered unthrottling
            if is_bottom and same_height_count >= STALL_LIMIT and no_new_turns >= (STALL_LIMIT + 50):
                print(f"[*] Đã chạm đáy trang thực sự ({cur_scroll_height:,} px) sau {STALL_LIMIT} lần thử kiên nhẫn.", flush=True)
                break

        # ONLY TAKE A SCREENSHOT HERE (single shot when finished / stalled at bottom)
        try:
            print("[*] Chụp ảnh xác nhận trạng thái đáy trang theo yêu cầu...")
            ss = await cdp.command('Page.captureScreenshot', {'format': 'jpeg', 'quality': 75})
            img_data = base64.b64decode(ss['data'])
            ss_out = ARTIFACT_DIR / "final_feed_bottom.jpg"
            ss_out.write_bytes(img_data)
            (ROOT.parent / "data" / "facebook_cases" / "su-ta-va-ho" / "final_feed_bottom.jpg").write_bytes(img_data)
            print(f"[+] Đã lưu ảnh chụp đáy trang tại: {ss_out}")
        except Exception as e:
            print(f"[!] Không thể chụp ảnh đáy: {e}")

        update_indexes(posts_ordered, OUTPUT_DIR, target_url)
        print(f"\n[+] HOÀN TẤT CÀO THÔ! Tổng cộng: {len(posts_ordered)} bài viết.", flush=True)

        print("[*] Tự động đồng bộ chuẩn hoá sang clean_txt...")
        try:
            sync_clean_txt()
        except Exception as e:
            print(f"[!] Lỗi khi đồng bộ clean_txt: {e}")

    finally:
        await cdp.close()


if __name__ == '__main__':
    asyncio.run(crawl())
