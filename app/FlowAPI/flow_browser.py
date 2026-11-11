# -*- coding: utf-8 -*-
"""
flow_browser.py — Google Flow (Whisk) client chạy qua trình duyệt thật (Playwright)
===================================================================================

Vì Google Flow chặn request không đến từ trình duyệt thật (bot detection), cách
dùng đáng tin cậy nhất là điều khiển Chrome thật bằng Playwright, nạp cookie,
mở flow.google.com, rồi gọi các RPC ngay trong ngữ cảnh trang (fetch trong
browser). Browser sẽ tự lo cookie, token 'at' và chống bot.

Các chức năng (giống flow_api.py):
  1. Tạo project mới               -> RPC "jHPbke"
  2. Tạo nhân vật / đổi tên        -> RPC "C4BZMd" / "rzMKMb"
  3/4/5. Tạo ảnh 0/1/2 reference   -> RPC "ogiZ0b"
"""

import json
import re
import random
import time
import urllib.parse
import uuid
from playwright.sync_api import sync_playwright

ENDPOINT = "https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute"
BL = "boq_labs-ai-sandbox-frontend_20261030.00_p2"
HL = "vi"
MODEL = "BELUGA"

RPC_CREATE_PROJECT = "jHPbke"
RPC_CREATE_CHARACTER = "C4BZMd"
RPC_RENAME_CHARACTER = "rzMKMb"
RPC_GENERATE_IMAGE = "ogiZ0b"
RPC_LIST_PROJECTS = "UpteDb"

_JS_FETCH = """
async (args) => {
  const { rpcid, payloadJson, at, fSid, sourcePath } = args;
  const params = new URLSearchParams({
    rpcids: rpcid,
    'source-path': sourcePath,
    bl: '%BL%',
    'f.sid': fSid,
    hl: '%HL%',
    _reqid: String(Math.floor(Math.random() * 9000000) + 1000000),
    rt: 'c'
  });
  const body = new URLSearchParams();
  body.append('f.req', JSON.stringify([[ [rpcid, payloadJson, null, 'generic'] ]]));
  if (at) body.append('at', at);
  const resp = await fetch('https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute?' + params.toString(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8' },
    body: body.toString(),
    credentials: 'include'
  });
  return await resp.text();
}
""".replace("%BL%", BL).replace("%HL%", HL)


_ANTI_DETECT_JS = """
// Ẩn dấu hiệu automation để Google cho phép đăng nhập
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'vi'] });
"""

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled",
                "--no-first-run", "--no-default-browser-check",
                "--disable-infobars"]


class FlowBrowserClient:
    """Client chạy trong trình duyệt thật."""

    def __init__(self, cookie_path=None, headless=False, channel="chrome",
                 profile_dir=None):
        self.cookies = None
        if cookie_path:
            with open(cookie_path, "r", encoding="utf-8") as f:
                self.cookies = json.load(f)
        self.headless = headless
        self.channel = channel
        self.profile_dir = profile_dir
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.at = None
        self.f_sid = None

    def start(self):
        self.pw = sync_playwright().start()
        if self.profile_dir:
            # Dùng hồ sơ Chrome riêng: đăng nhập 1 lần, các lần sau tự dùng lại
            self.context = self.pw.chromium.launch_persistent_context(
                self.profile_dir, channel=self.channel, headless=self.headless,
                args=_LAUNCH_ARGS, ignore_default_args=["--enable-automation"])
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        else:
            self.browser = self.pw.chromium.launch(
                channel=self.channel, headless=self.headless,
                args=_LAUNCH_ARGS, ignore_default_args=["--enable-automation"])
            self.context = self.browser.new_context()
            self.page = self.context.new_page()

            # Mở trang trước để context có URL hợp lệ
            self.page.goto("https://flow.google.com/", wait_until="domcontentloaded")
            self.page.wait_for_timeout(1000)

            if self.cookies:
                cks = [{"name": c["name"], "value": c["value"],
                        "url": "https://flow.google.com/"} for c in self.cookies]
                self.context.add_cookies(cks)

        # Ẩn dấu hiệu automation để Google cho đăng nhập
        self.context.add_init_script(_ANTI_DETECT_JS)

        self.page.on("request", self._capture)
        self.page.goto("https://flow.google.com/", wait_until="domcontentloaded")
        self.page.wait_for_timeout(3000)

    def wait_for_login(self, timeout=300):
        """Chờ người dùng đăng nhập thủ công (poll tới khi app nạp xong)."""
        if self.f_sid is not None:
            return True
        print("\n>>> Cửa sổ Chrome đang mở. Hãy ĐĂNG NHẬP flow.google.com (bấm Sign in / Đăng nhập).")
        print("    Đang chờ... (script tự nhận diện khi bạn vào được app)")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.f_sid is not None:
                print(">>> Đã đăng nhập thành công!\n")
                return True
            time.sleep(2)
        print(">>> Hết thời gian chờ, chưa thấy đăng nhập.")
        return False

    def save_cookies(self, path):
        """Tự xuất cookie hiện tại của trình duyệt ra file JSON (đúng định dạng)."""
        cookies = self.context.cookies()
        out = []
        for c in cookies:
            out.append({
                "domain": c.get("domain", ""),
                "name": c["name"],
                "value": c["value"],
                "path": c.get("path", "/"),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=4)
        return out

    def _capture(self, req):
        if "batchexecute" in req.url:
            if self.at is None:
                post = req.post_data or ""
                m = re.search(r"at=([^&]+)", post)
                if m:
                    self.at = urllib.parse.unquote(m.group(1))
            if self.f_sid is None:
                m = re.search(r"f\.sid=([^&]+)", req.url)
                if m:
                    self.f_sid = m.group(1)

    def close(self):
        if self.browser:
            self.browser.close()
        elif self.context:
            self.context.close()
        if self.pw:
            self.pw.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.close()

    def _batchexecute(self, rpcid, payload, source_path="/"):
        payload_json = json.dumps(payload, ensure_ascii=False)
        body = self.page.evaluate(_JS_FETCH, {
            "rpcid": rpcid,
            "payloadJson": payload_json,
            "at": self.at,
            "fSid": self.f_sid,
            "sourcePath": source_path,
        })
        return self._parse_response(body)

    @staticmethod
    def _parse_response(body):
        body = body.strip()
        if body.startswith(")]}'"):
            body = body[4:]
        out = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line[0] not in "[{":
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                        try:
                            out.append(json.loads(item[2]))
                        except Exception:
                            out.append(item[2])
        return out

    # -- 1. Tạo project ----------------------------------------------------
    def create_project(self, name):
        payload = ["projects/*", [None, [name]], [None, 22]]
        res = self._batchexecute(RPC_CREATE_PROJECT, payload, source_path="/")
        if res and isinstance(res[0], list) and len(res[0]) >= 2:
            return res[0][0], res[0][1][0]
        return res

    # -- 2. Tạo / đổi tên nhân vật -----------------------------------------
    def create_character(self, project_id, name):
        payload = [[project_id, None, None, [1, name, []]]]
        res = self._batchexecute(RPC_CREATE_CHARACTER, payload,
                                 source_path=f"/project/{project_id}/character")
        # response: [[[project_id, char_id, null, [1, name, []], ...]]]
        try:
            char = res[0][0]
            return char[0], char[1], char[3][1]
        except (IndexError, TypeError):
            return res

    def rename_character(self, project_id, character_id, new_name):
        payload = [[project_id, character_id, None, [1, new_name]],
                   [["entity_info.display_name"]]]
        return self._batchexecute(RPC_RENAME_CHARACTER, payload,
                                  source_path=f"/project/{project_id}/character/{character_id}")

    # -- 3/4/5. Tạo ảnh -----------------------------------------------------
    def generate_image(self, project_id, prompt, character_refs=None,
                       seed=None, count=1, mode=2, ref_token=None):
        seed = seed if seed is not None else random.randint(0, 2**31 - 1)
        refs = []
        if character_refs:
            for c in character_refs:
                if isinstance(c, (tuple, list)):
                    refs.append((c[0], c[1] if len(c) > 1 else c[0]))
                else:
                    refs.append((c, c))

        context = [None, 22, None, None, None, project_id,
                   None, None, None, None, [ref_token, 1] if ref_token else []]

        if refs:
            parts = []
            for i, (cid, cname) in enumerate(refs):
                if i > 0:
                    parts.append([" "])
                parts.append([None, [None, None, [cid, cname]]])
            parts.append([" " + prompt])
            prompt_parts = [parts]
            char_ids = [[cid] for cid, _ in refs]
        else:
            prompt_parts = [[[prompt]]]
            char_ids = None

        request = [None, None, None, seed, mode, MODEL, None, context,
                   prompt_parts, None, char_ids, None,
                   str(uuid.uuid4()).upper(), str(uuid.uuid4()).upper()]

        payload = [None, [request], count, context, [str(uuid.uuid4()).upper()]]

        source_path = f"/project/{project_id}"
        res = self._batchexecute(RPC_GENERATE_IMAGE, payload, source_path=source_path)
        return self._extract_images(res)

    # -- Tạo ảnh bằng cách điều khiển UI (CÁCH ĐANG HOẠT ĐỘNG) ----------------
    # LƯU Ý: generate_image() gọi RPC thủ công bị Google chặn bằng lỗi
    # PUBLIC_ERROR_UNUSUAL_ACTIVITY, vì request tạo ảnh cần token chống lạm dụng
    # (0cAFcWeA...) + header x-browser-validation do frontend tự sinh ra.
    # Cách duy nhất hoạt động: gõ prompt + bấm nút Generate thật trong UI.
    def generate_image_via_ui(self, prompt, wait_seconds=60):
        """Tạo ảnh bằng UI thật: gõ prompt vào ô nhập + bấm nút Generate.

        - Ô nhập:  div[role=textbox].ProseMirror
        - Nút:     button.generate-icon-button (phải dùng click(force=True))
        - Sau khi bấm, ảnh được tạo ~30-90s. Cần poll kết quả (ảnh mới xuất
          hiện trong grid / lưới ảnh của project).
        """
        box = self.page.locator(".ProseMirror")
        if box.count() == 0:
            raise RuntimeError("Không tìm thấy ô nhập prompt (.ProseMirror)")
        box.first.click()
        self.page.wait_for_timeout(300)
        self.page.keyboard.insert_text(prompt)
        self.page.wait_for_timeout(500)
        self.page.keyboard.press("Enter")          # commit prompt
        self.page.wait_for_timeout(1500)
        self.page.locator(".generate-icon-button").first.click(force=True)
        self.page.wait_for_timeout(wait_seconds * 1000)

    @staticmethod
    def _extract_images(res):
        images = []
        if res and isinstance(res[0], list):
            for media in res[0]:
                if not (isinstance(media, list) and len(media) >= 7):
                    continue
                image_id = media[0]
                info = media[6]
                prompt = url = None
                width = height = None
                if isinstance(info, list) and len(info) > 0 and isinstance(info[0], list):
                    data = info[0]
                    if len(data) > 13:
                        prompt = data[7]
                        url = data[13]
                if isinstance(info, list) and len(info) > 2 and isinstance(info[2], list) and len(info[2]) >= 2:
                    width, height = info[2][0], info[2][1]
                images.append({"image_id": image_id, "prompt": prompt,
                               "url": url, "width": width, "height": height})
        return images


if __name__ == "__main__":
    # Mở Chrome với hồ sơ riêng (đăng nhập 1 lần, các lần sau tự dùng lại).
    # Sau khi đăng nhập, script tự xuất cookie mới ra cookie.txt.
    with FlowBrowserClient(profile_dir=r"c:\Users\leath\Downloads\test\flow_profile",
                           headless=False) as c:
        if not c.wait_for_login(timeout=300):
            print("Chưa đăng nhập, thoát.")
            raise SystemExit(1)

        # Tự xuất cookie mới ra cookie.txt (không cần extension)
        n = len(c.save_cookies(r"c:\Users\leath\Downloads\test\cookie.txt"))
        print(f"Đã xuất {n} cookie mới vào cookie.txt")

        print("f_sid:", c.f_sid)
        print("at:", (c.at or "")[:30], "...")
        print("List projects:")
        print(json.dumps(c._batchexecute(RPC_LIST_PROJECTS,
                                         ["projects/*", 21, None, None, None, None, [1]],
                                         source_path="/"),
                         ensure_ascii=False, indent=2)[:3000])
