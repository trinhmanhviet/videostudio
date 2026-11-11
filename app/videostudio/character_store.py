"""Persistent Character Roster for VideoStudio Meme & Comedy Animations.

Maintains persistent character definitions (costumes, hair/accessories with custom offsets,
faces, voices, and aliases) across video episodes.
"""
from __future__ import annotations

from .paths import DATA_ROOT
import json
import re
import unicodedata
import copy
import math
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE_PATH = DATA_ROOT/'characters.json'
_ROSTER_LOCK=threading.RLock()


def _offset(value):
    if not isinstance(value,dict):raise ValueError('Character offsets must be objects')
    for field in ('dx','dy','scale','rotation'):
        if field in value:
            number=value[field]
            if type(number) not in (int,float) or not math.isfinite(number) or (field=='scale' and number<=0):
                raise ValueError('Character offsets require finite numbers and positive scale')


def validate_roster(characters):
    if not isinstance(characters,list):raise ValueError('Character roster must be a list')
    seen=set()
    for c in characters:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not re.fullmatch(r'[a-z_][a-z0-9_]{0,63}',c['id']):raise ValueError('Invalid character ID')
        if c['id'] in seen:raise ValueError('Duplicate character ID')
        seen.add(c['id'])
        for field in ('name','costume','default_face','voice','description'):
            if field in c and not isinstance(c[field],str):raise ValueError(field+' must be text')
        if not isinstance(c.get('aliases',[]),list) or any(not isinstance(a,str) for a in c.get('aliases',[])):raise ValueError('aliases must be text list')
        acc=c.get('acc',[])
        if not isinstance(acc,list):raise ValueError('acc must be a list')
        for item in acc:
            aid=item.get('id') if isinstance(item,dict) else item
            if not isinstance(aid,str) or not aid:raise ValueError('Accessory ID must be text')
            if isinstance(item,dict):_offset(item)
        _offset(c.get('costume_offset',{}))
        offsets=c.get('acc_offsets',{})
        if not isinstance(offsets,dict):raise ValueError('acc_offsets must be an object')
        for value in offsets.values():_offset(value)
    return characters

DEFAULT_CHARACTERS = [
    {
        "id": "bo",
        "name": "Bố",
        "aliases": ["bố", "ông bố", "ba", "cha", "tía", "phụ thân", "father", "dad"],
        "costume": "ao_ba_lo_trang",
        "costume_offset": {"dx": 0, "dy": 0, "scale": 1.0},
        "acc": [
            {"id": "toc_dung_nguoc", "dx": 0, "dy": -8, "scale": 1.0, "rotation": 0},
            {"id": "rau_mep", "dx": 0, "dy": 0, "scale": 1.0, "rotation": 0}
        ],
        "default_face": "gian",
        "voice": "clone:18cad821-0d87-461f-a443-d45db92e36e9",
        "description": "Người bố khó tính, thích yên tĩnh, hay quát tháo nhưng dễ bị hớ"
    },
    {
        "id": "toi",
        "name": "Tôi",
        "aliases": ["tôi", "con trai", "người con", "thằng con", "con", "nam", "son"],
        "costume": "ao_phong_xanh",
        "costume_offset": {"dx": 0, "dy": 0, "scale": 1.0},
        "acc": [
            {"id": "toc_hui_cua", "dx": 0, "dy": -3, "scale": 1.02, "rotation": 0}
        ],
        "default_face": "noi",
        "voice": "clone:18cad821-0d87-461f-a443-d45db92e36e9",
        "description": "Người con trai kể chuyện, thanh niên năng động"
    },
    {
        "id": "me",
        "name": "Mẹ",
        "aliases": ["mẹ", "má", "bà mẹ", "vợ", "mẹ tôi", "mother", "mom"],
        "costume": "ao_ba_ba_hoa",
        "costume_offset": {"dx": 0, "dy": 0, "scale": 1.0},
        "acc": [
            {"id": "toc_bui_cao", "dx": 0, "dy": -8, "scale": 1.0, "rotation": 0}
        ],
        "default_face": "cuoi",
        "voice": "clone:18cad821-0d87-461f-a443-d45db92e36e9",
        "description": "Người mẹ quyền lực, tháo vát, tiếng nói quyết định trong nhà"
    },
    {
        "id": "hang_xom",
        "name": "Bác hàng xóm",
        "aliases": ["hàng xóm", "bác hàng xóm", "ông hàng xóm", "chú hàng xóm", "neighbor"],
        "costume": "so_mi_caro",
        "costume_offset": {"dx": 0, "dy": 0, "scale": 1.0},
        "acc": [
            {"id": "hoi_toc_bac", "dx": 0, "dy": -4, "scale": 1.0, "rotation": 0},
            {"id": "kinh_can", "dx": 0, "dy": 0, "scale": 1.0, "rotation": 0}
        ],
        "default_face": "soc",
        "voice": "clone:18cad821-0d87-461f-a443-d45db92e36e9",
        "description": "Bác hàng xóm nhiều chuyện, hay hóng hớt khu phố"
    }
]


def _normalize_tokens(text: str) -> list[str]:
    """Lowercase, strip accents, and return clean word tokens."""
    if not text:
        return []
    text = text.lower().strip()
    nfkd = unicodedata.normalize('NFKD', text)
    no_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', no_accents)
    return [t for t in cleaned.split() if t]


def _normalize_phrase(text: str) -> str:
    """Normalize text into space-separated clean words."""
    return " ".join(_normalize_tokens(text))


def _normalize_name(text: str) -> str:
    """Normalize text without spaces for strict alphanumeric comparison."""
    tokens = _normalize_tokens(text)
    return "".join(tokens)


def _load_roster(path: Path | str | None = None) -> list[dict]:
    """Load character roster from JSON file or create with defaults."""
    target = Path(path) if path else DEFAULT_STORE_PATH
    if target.is_file():
        try:data=json.loads(target.read_text(encoding='utf-8'))
        except ValueError as error:raise ValueError('Character file is invalid; original preserved: '+str(target)) from error
        return validate_roster(data.get('characters') if isinstance(data,dict) else data)
    # Initialize defaults
    save_roster(DEFAULT_CHARACTERS, target)
    return copy.deepcopy(DEFAULT_CHARACTERS)


def load_roster(path: Path | str | None = None) -> list[dict]:
    with _ROSTER_LOCK:return _load_roster(path)


def save_roster(characters: list[dict], path: Path | str | None = None) -> None:
    """Safely atomic write characters roster."""
    validate_roster(characters)
    content=json.dumps({'characters':characters},ensure_ascii=False,indent=2,allow_nan=False)
    with _ROSTER_LOCK:
        target = Path(path) if path else DEFAULT_STORE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix('.tmp.'+uuid.uuid4().hex)
        try:temp.write_text(content,encoding='utf8');temp.replace(target)
        finally:temp.unlink(missing_ok=True)


def edit_roster(change,path=None):
    with _ROSTER_LOCK:
        updated=change(copy.deepcopy(load_roster(path)))
        save_roster(updated,path)
        return updated


def find_matching_character(cid_or_name: str, roster: list[dict]) -> dict | None:
    """Match a role identifier or name against character roster."""
    if not cid_or_name:
        return None
    raw_lower = cid_or_name.lower().strip()
    norm = _normalize_name(cid_or_name)
    phrase = _normalize_phrase(cid_or_name)
    query_tokens = set(_normalize_tokens(cid_or_name))

    # 1. Exact ID match
    for char in roster:
        if char['id'].lower() == raw_lower:
            return char

    # 2. Exact or normalized Name match
    for char in roster:
        char_name = char.get('name', '')
        if char_name.lower() == raw_lower or _normalize_name(char_name) == norm:
            return char

    # 3. Exact Alias match
    for char in roster:
        for alias in char.get('aliases', []):
            if alias.lower() == raw_lower or _normalize_name(alias) == norm:
                return char

    # 4. Word boundary / whole phrase match
    # Example: "bác hàng xóm" contains "hang xom"; "ông bố" contains "bo"
    # We do NOT do raw substring so "bác sĩ" doesn't falsely match "ba".
    if phrase:
        for char in roster:
            char_phrase = _normalize_phrase(char.get('name', ''))
            if char_phrase and re.search(r'(?:\b|^)' + re.escape(char_phrase) + r'(?:\b|$)', phrase):
                return char
            for alias in char.get('aliases', []):
                alias_phrase = _normalize_phrase(alias)
                if alias_phrase and re.search(r'(?:\b|^)' + re.escape(alias_phrase) + r'(?:\b|$)', phrase):
                    return char

    return None


def apply_roster_to_cast(cast: dict, roster: list[dict] | None = None) -> dict:
    """Lock or enhance script cast with characters defined in the persistent roster.
    
    If a character is matched in the roster:
      - Inherit their exact costume and costume_offset.
      - Inherit their exact accessories (with dx, dy, scale, rotation offsets).
      - Retain or adapt default face if specified.
    If a character is not in the roster:
      - Preserve the LLM-generated appearance.
    """
    if roster is None:
        roster = load_roster()

    updated_cast = {}
    for cid, card in cast.items():
        matched = find_matching_character(cid, roster) or find_matching_character(card.get('name', ''), roster)
        if matched:
            new_card = dict(card)
            new_card['name'] = card.get('name') or matched.get('name',cid)
            new_card['costume'] = matched.get('costume', card.get('costume'))
            if matched.get('default_face'):new_card['face']=matched['default_face']
            if 'costume_offset' in matched:
                new_card['costume_offset'] = matched['costume_offset']
            # Accessories: full objects with offsets
            new_card['acc'] = matched.get('acc', [])
            if 'acc_offsets' in matched:
                new_card['acc_offsets'] = matched['acc_offsets']
            if not new_card.get('voice') and matched.get('voice'):
                new_card['voice'] = matched['voice']
            updated_cast[cid] = new_card
        else:
            updated_cast[cid] = card

    return updated_cast


def describe_roster_for_prompt(roster: list[dict] | None = None) -> str:
    """Format roster summary for LLM prompt."""
    if roster is None:
        roster = load_roster()
    items = []
    for c in roster:
        acc_names = [a['id'] if isinstance(a, dict) else a for a in c.get('acc', [])]
        aliases = ', '.join(c.get('aliases', []))
        items.append(
            f"- ID: {c['id']} | Tên: {c['name']} (bí danh: {aliases}) | "
            f"Trang phục: {c.get('costume')} | Phụ kiện: {', '.join(acc_names) or 'không'} | "
            f"Mô tả: {c.get('description', '')}"
        )
    return "\n".join(items)
