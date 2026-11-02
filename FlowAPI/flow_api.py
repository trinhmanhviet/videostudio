# -*- coding: utf-8 -*-
"""
flow_api.py — Google Flow (Whisk) API client
============================================

Trích xuất các POST method từ file network.har (Google Flow / flow.google.com)
và cung cấp các hàm gọi API tương ứng cho từng chức năng:

  1. Tạo project mới              -> RPC "jHPbke"
  2. Tạo nhân vật (character)     -> RPC "C4BZMd"
     Đổi tên nhân vật              -> RPC "rzMKMb"
  3. Tạo ảnh với 1 ảnh reference  -> RPC "ogiZ0b" (1 character ref)
  4. Tạo ảnh với 2 ảnh reference  -> RPC "ogiZ0b" (2 character refs)
  5. Tạo ảnh không dùng reference -> RPC "ogiZ0b" (plain text prompt)

Tất cả request đều đi qua endpoint chung:
    POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute

Body (application/x-www-form-urlencoded):
    f.req = [[["<RPCID>", "<payload_json_string>", null, "generic"]]]
    at    = "<sapisidhash>:<timestamp_ms>"   (XSRF token)

Xác thực: cookie (từ cookie.txt) + tham số "at" tính từ cookie SAPISID.
"""

import base64
import hashlib
import json
import random
import re
import time
import urllib.parse
import uuid

try:
    import requests
except ImportError:
    requests = None

# ---------------------------------------------------------------------------
# Hằng số (trích xuất từ network.har)
# ---------------------------------------------------------------------------
ENDPOINT = "https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute"
ORIGIN = "https://flow.google.com"

BL = "boq_labs-ai-sandbox-frontend_20261030.00_p2"  # build label
F_SID = "-2881063480834598835"                       # session id (đổi theo phiên)
HL = "vi"

# RPC ids (đã trích xuất từ network.har)
RPC_CREATE_PROJECT = "jHPbke"
RPC_LIST_PROJECTS = "UpteDb"
RPC_CREATE_CHARACTER = "C4BZMd"
RPC_RENAME_CHARACTER = "rzMKMb"
RPC_GENERATE_IMAGE = "ogiZ0b"
RPC_LIST_CHARACTERS = "ngNC2"

MODEL = "BELUGA"
MODE_PROJECT_IMAGE = 2     # tạo ảnh ở mức project
MODE_CHARACTER_AVATAR = 3  # tạo ảnh đại diện cho character


# ---------------------------------------------------------------------------
# 1. TRÍCH XUẤT POST METHOD TỪ network.har
# ---------------------------------------------------------------------------
def extract_post_methods(har_path):
    """Trích xuất toàn bộ POST request từ file HAR.

    Trả về list dict gồm: index, rpcid, url, source_path, payload (đã decode).
    """
    with open(har_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = []
    for i, entry in enumerate(data["log"]["entries"]):
        req = entry["request"]
        if req["method"].upper() != "POST":
            continue
        url = req["url"]
        m = re.search(r"rpcids=([^&]+)", url)
        rpcid = m.group(1) if m else None
        sp = re.search(r"source-path=([^&]+)", url)
        source_path = urllib.parse.unquote(sp.group(1)) if sp else ""

        post_text = req.get("postData", {}).get("text", "")
        form = urllib.parse.parse_qs(post_text)

        payload = None
        if "f.req" in form:
            try:
                outer = json.loads(form["f.req"][0])
                payload = json.loads(outer[0][0][1])
            except Exception:
                payload = form["f.req"][0]

        results.append({
            "index": i,
            "rpcid": rpcid,
            "url": url,
            "source_path": source_path,
            "payload": payload,
            "at": form.get("at", [None])[0],
            "form": form,
        })
    return results


def extract_at_from_har(har_path):
    """Lấy XSRF token 'at' từ HAR (dùng làm tham chiếu)."""
    for p in extract_post_methods(har_path):
        if p["at"]:
            return p["at"]
    return None


# ---------------------------------------------------------------------------
# 2. XÁC THỰC (cookie + XSRF token 'at')
# ---------------------------------------------------------------------------
def load_cookies(cookie_path):
    """Đọc cookie.txt -> dict {name: value}.

    Hỗ trợ cả 2 định dạng: JSON export (extension) và Netscape cookie file.
    """
    with open(cookie_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    cookies = {}
    if raw.startswith("["):
        for c in json.loads(raw):
            cookies[c["name"]] = c["value"]
    else:
        for line in raw.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies


def compute_at(sapisid, origin=ORIGIN, ts_ms=None):
    """Tính XSRF token 'at' cho batchexecute (thuật toán SAPISIDHASH của Google).

        hash = base64url( SHA1("<ts_ms> <SAPISID> <origin>") )  (bỏ padding '=')
        at   = "<hash>:<ts_ms>"
    """
    ts_ms = ts_ms or int(time.time() * 1000)
    msg = f"{ts_ms} {sapisid} {origin}"
    digest = hashlib.sha1(msg.encode("utf-8")).digest()
    hash_str = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{hash_str}:{ts_ms}"


# ---------------------------------------------------------------------------
# 3. CLIENT
# ---------------------------------------------------------------------------
class FlowClient:
    """Client gọi API Google Flow (flow.google.com)."""

    def __init__(self, cookies=None, cookie_path=None, sapisid=None,
                 at=None, f_sid=F_SID, bl=BL, hl=HL, session=None):
        self.f_sid = f_sid
        self.bl = bl
        self.hl = hl
        self._reqid = 4184621  # counter như trong HAR (tăng dần)
        self.session = session or (requests.Session() if requests else None)

        if cookies is None and cookie_path:
            cookies = load_cookies(cookie_path)
        self.cookies = cookies or {}

        self.sapisid = sapisid or self.cookies.get("SAPISID")
        self.at = at or (compute_at(self.sapisid) if self.sapisid else None)

    # -- helper gửi 1 RPC qua batchexecute ---------------------------------
    def _batchexecute(self, rpcid, payload, source_path="/"):
        """Đóng gói payload và gửi 1 RPC đến endpoint batchexecute."""
        if requests is None:
            raise RuntimeError("Cần cài đặt thư viện 'requests': pip install requests")

        # f.req = [[["rpcid","<json_payload>",null,"generic"]]]
        freq_inner = [rpcid, json.dumps(payload, ensure_ascii=False), None, "generic"]
        freq = json.dumps([[freq_inner]], ensure_ascii=False)

        self._reqid += 100000
        params = {
            "rpcids": rpcid,
            "source-path": source_path,
            "bl": self.bl,
            "f.sid": self.f_sid,
            "hl": self.hl,
            "_reqid": str(self._reqid),
            "rt": "c",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/156.0.0.0 Safari/537.36"),
        }
        data = {"f.req": freq}
        if self.at:
            data["at"] = self.at

        resp = self.session.post(
            ENDPOINT, params=params, headers=headers, data=data,
            cookies=self.cookies,
        )
        resp.raise_for_status()
        return self._parse_response(resp.text)

    @staticmethod
    def _parse_response(body):
        """Parse response dạng: )]}'\\n\\n<num>\\n[[\"wrb.fr\",\"rpcid\",\"payload\",...]]"""
        body = body.strip()
        if body.startswith(")]}'"):
            body = body[4:]
        payloads = []
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
                    if (isinstance(item, list) and len(item) >= 3
                            and item[0] == "wrb.fr"):
                        try:
                            payloads.append(json.loads(item[2]))
                        except Exception:
                            payloads.append(item[2])
        return payloads

    # -- 1. Tạo project mới -------------------------------------------------
    def create_project(self, name):
        """Tạo project mới, trả về (project_id, name)."""
        payload = ["projects/*", [None, [name]], [None, 22]]
        res = self._batchexecute(RPC_CREATE_PROJECT, payload, source_path="/")
        # response mẫu: [project_id, [name]]
        if res and isinstance(res[0], list) and len(res[0]) >= 2:
            return res[0][0], res[0][1][0]
        return res

    # -- 2. Tạo nhân vật / đổi tên nhân vật ---------------------------------
    def create_character(self, project_id, name):
        """Tạo nhân vật mới, trả về (project_id, character_id, name)."""
        payload = [[project_id, None, None, [1, name, []]]]
        res = self._batchexecute(
            RPC_CREATE_CHARACTER, payload,
            source_path=f"/project/{project_id}/character",
        )
        # response mẫu: [[project_id, char_id, null, [1, name, []], ...]]
        if res and isinstance(res[0], list) and len(res[0]) >= 4:
            return res[0][0], res[0][1], res[0][3][1]
        return res

    def rename_character(self, project_id, character_id, new_name):
        """Đổi tên nhân vật (cập nhật field entity_info.display_name)."""
        payload = [
            [project_id, character_id, None, [1, new_name]],
            [["entity_info.display_name"]],
        ]
        res = self._batchexecute(
            RPC_RENAME_CHARACTER, payload,
            source_path=f"/project/{project_id}/character/{character_id}",
        )
        return res

    # -- 3/4/5. Tạo ảnh (0 / 1 / 2 reference) --------------------------------
    def generate_image(self, project_id, prompt, character_refs=None,
                       seed=None, count=1, mode=MODE_PROJECT_IMAGE,
                       ref_token=None):
        """Tạo ảnh.

        Parameters
        ----------
        project_id : str
            id của project.
        prompt : str
            nội dung mô tả ảnh (text prompt).
        character_refs : list, optional
            danh sách nhân vật dùng làm ảnh reference (mỗi nhân vật có 1 ảnh
            đại diện => ảnh reference):
              - None hoặc []                       -> KHÔNG dùng reference
              - [("char_id1", "Tên 1")]            -> 1 ảnh reference
              - [("char_id1","Tên 1"),("char_id2","Tên 2")] -> 2 ảnh reference
        ref_token : str, optional
            token ảnh reference dạng "0cAFcWeA..." (opaque, nằm ở trường
            context). Nếu không truyền, context sẽ để danh sách rỗng.
        """
        seed = seed if seed is not None else random.randint(0, 2**31 - 1)

        # chuẩn hoá danh sách reference thành list (char_id, char_name)
        refs = []
        if character_refs:
            for c in character_refs:
                if isinstance(c, (tuple, list)):
                    refs.append((c[0], c[1] if len(c) > 1 else c[0]))
                else:
                    refs.append((c, c))

        # context (trường [7] và [3]): project id + token ảnh reference
        context = [None, 22, None, None, None, project_id,
                   None, None, None, None,
                   [ref_token, 1] if ref_token else []]

        # prompt parts (trường [8])
        if refs:
            parts = []
            for i, (cid, cname) in enumerate(refs):
                if i > 0:
                    parts.append([" "])                     # text ngăn cách
                parts.append([None, [None, None, [cid, cname]]])  # char ref
            parts.append([" " + prompt])                    # text chính
            prompt_parts = [parts]
            char_ids = [[cid] for cid, _ in refs]
        else:
            prompt_parts = [[[prompt]]]                     # text thuần
            char_ids = None

        request = [
            None, None, None,        # [0][1][2]
            seed,                    # [3] seed
            mode,                    # [4] 2=project image, 3=character avatar
            MODEL,                   # [5] model
            None,                    # [6]
            context,                 # [7] context
            prompt_parts,            # [8] prompt
            None,                    # [9]
            char_ids,                # [10] danh sách character id (hoặc null)
            None,                    # [11]
            str(uuid.uuid4()).upper(),   # [12] uuid client
            str(uuid.uuid4()).upper(),   # [13] uuid client
        ]

        payload = [
            None,                                  # [0]
            [request],                             # [1] danh sách request generate
            count,                                 # [2] số lượng ảnh
            context,                               # [3] context (lặp lại)
            [str(uuid.uuid4()).upper()],           # [4] uuid cuối (project-level)
        ]

        source_path = f"/project/{project_id}"
        if mode == MODE_CHARACTER_AVATAR and refs:
            source_path = f"/project/{project_id}/character/{refs[0][0]}"

        res = self._batchexecute(RPC_GENERATE_IMAGE, payload, source_path=source_path)
        return self._extract_generated_images(res)

    @staticmethod
    def _extract_generated_images(res):
        """Rút danh sách ảnh đã sinh từ response của ogiZ0b."""
        images = []
        if res and isinstance(res[0], list):
            for media in res[0]:
                if isinstance(media, list) and len(media) >= 7:
                    info = media[6]
                    if isinstance(info, list) and len(info) >= 15:
                        images.append({
                            "image_id": media[0],
                            "prompt": info[7],
                            "url": info[13],
                            "width": info[9][0] if info[9] else None,
                            "height": info[9][1] if info[9] else None,
                        })
        return images


# ---------------------------------------------------------------------------
# 4. DEMO / PAYLOAD MẪU (không cần mạng)
# ---------------------------------------------------------------------------
def demo_payloads():
    """In ra payload mẫu cho từng chức năng (không gửi request)."""
    print("=" * 70)
    print("1) Tạo project mới (jHPbke)")
    print(json.dumps(["projects/*", [None, ["Tên project"]], [None, 22]],
                     ensure_ascii=False, indent=2))

    print("\n2) Tạo nhân vật (C4BZMd)")
    print(json.dumps([["<project_id>", None, None, [1, "Nhân vật", []]]],
                     ensure_ascii=False, indent=2))

    print("\n2b) Đổi tên nhân vật (rzMKMb)")
    print(json.dumps([["<project_id>", "<char_id>", None, [1, "Tên mới"]],
                      [["entity_info.display_name"]]],
                     ensure_ascii=False, indent=2))

    print("\n3/4/5) Tạo ảnh (ogiZ0b) - cấu trúc trường prompt [8]")
    print("  - Không reference:")
    print(json.dumps([[["mô tả ảnh"]]], ensure_ascii=False))
    print("  - 1 reference:")
    print(json.dumps([[[[None, [None, None, ["<char_id>", "Tên"]], " mô tả"]]]],
                     ensure_ascii=False))
    print("  - 2 reference:")
    print(json.dumps([[[[None, [None, None, ["<char_id1>", "A"]], " mô tả ",
                         [None, [None, None, ["<char_id2>", "B"]]], " "]]]],
                     ensure_ascii=False))


if __name__ == "__main__":
    demo_payloads()
