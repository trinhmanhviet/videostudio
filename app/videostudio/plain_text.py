"""Turn a script pasted as Markdown into plain text, so TTS never reads the markup ("sao sao")."""
import re

_ESCAPE = re.compile(r'\\([\\`*_{}\[\]()#+\-.!~|>])')
_FENCE = re.compile(r'^\s*(```|~~~)')
_RULE = re.compile(r'^\s*(?:([-*_])(?:\s*\1){2,}|={3,})\s*$')
_TABLE_RULE = re.compile(r'^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$')
_QUOTE = re.compile(r'^\s*(?:>\s*)+')
_HEADING = re.compile(r'^\s*#{1,6}\s+(.*?)(?:\s+#+)?\s*$')
_BULLET = re.compile(r'^\s*[-*+•]\s+(?:\[[ xX]\]\s+)?')
_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_LINK = re.compile(r'\[([^\]]+)\]\([^)]*\)')
_BREAK = re.compile(r'<br\s*/?>', re.I)
_CODE = re.compile(r'`+([^`]+)`+')
_STRIKE = re.compile(r'~~(.+?)~~')
_UNDER_BOLD = re.compile(r'(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)')
_UNDER_ITALIC = re.compile(r'(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)')
_STAR = re.compile(r'(?<!\d)\*|\*(?!\d)')  # keeps 2*3
_SPACES = re.compile(r'[ \t]{2,}')


def _table_row(line):
    text = line.strip()
    if text.startswith('|') and text.endswith('|') and text.count('|') >= 2:
        return ', '.join(cell.strip() for cell in text.strip('|').split('|') if cell.strip())
    return line


def _clean_line(line):
    line = _ESCAPE.sub(r'\1', line)
    line = _table_row(line)
    line = _QUOTE.sub('', line)
    heading = _HEADING.match(line)
    if heading:
        line = heading.group(1)
    line = _BULLET.sub('', line)
    line = _IMAGE.sub('', line)
    line = _LINK.sub(r'\1', line)
    line = _BREAK.sub(' ', line)
    line = _CODE.sub(r'\1', line).replace('`', '')
    line = _STRIKE.sub(r'\1', line)
    line = _UNDER_BOLD.sub(r'\1', line)
    line = _UNDER_ITALIC.sub(r'\1', line)
    line = _STAR.sub('', line)
    return _SPACES.sub(' ', line).strip()


def strip_markdown(text):
    """Remove the markup and keep the words and the line breaks; lines that were only markup disappear."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            out.append('')
        elif not (_FENCE.match(line) or _RULE.match(line) or _TABLE_RULE.match(line)):
            cleaned = _clean_line(line)
            if cleaned:
                out.append(cleaned)
    return '\n'.join(out).strip()


def is_user_script(request):
    return request.get('workflow_mode') == 'provided_narration' or request.get('meme_input_mode') == 'script'
