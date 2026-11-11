"""Post titles and captions for YouTube, Facebook and TikTok.

They are written by the same text provider as the video, from the finished
narration only, and stored next to the video as social.json. Failing to write
them never fails the video.
"""
import json
import re
import threading
import time
from pathlib import Path

FILE = 'social.json'
# Posts must make people stop scrolling: dramatic, suspenseful, built on real details from the narration.
DRAMA = ('Write in a dramatic, suspenseful, curiosity-driven voice that makes people stop scrolling and watch. '
         'Open with the strongest hook: a shocking detail, a tense moment or a burning question taken from the narration. '
         'Build tension and tease the twist, but never reveal the ending. ')
NO_HEDGING = ('Never use hedging phrases such as "được cho là", "bị cho là", "được cho rằng", "người ta cho rằng". '
              'State what the narration says directly. ')
NARRATION_LIMIT = 12000
_running = set()
_lock = threading.Lock()


def narration(job):
    checkpoints = job.get('checkpoints') or {}
    script = checkpoints.get('script') or {}
    text = script.get('narration') if isinstance(script, dict) else None
    if not isinstance(text, str) or not text.strip():
        text = (job.get('request') or {}).get('idea', '')
    return str(text).strip()


def video_title(job):
    checkpoints = job.get('checkpoints') or {}
    for stage in ('script', 'plan'):
        value = (checkpoints.get(stage) or {}).get('title') if isinstance(checkpoints.get(stage), dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str((job.get('request') or {}).get('project') or '').strip()


def prompt(job):
    text = narration(job)
    if len(text) > NARRATION_LIMIT:
        text = text[:NARRATION_LIMIT] + ' …'
    return ('Write social media post copy in Vietnamese for a finished video. Use only facts stated in the narration below; '
            'do not invent names, numbers, outcomes or claims. ' + DRAMA + NO_HEDGING +
            'Return JSON exactly {"youtube":{"title":str,"description":str,"tags":[str]},'
            '"facebook":{"caption":str,"hashtags":[str]},"tiktok":{"caption":str,"hashtags":[str]}}. '
            'youtube.title: at most 90 characters. youtube.description: 2-4 short paragraphs that summarise the story without giving away the ending. '
            'youtube.tags: 5-12 short tags without #. facebook.caption: a hook line and 2-3 short paragraphs ending with a question for the audience. '
            'facebook.hashtags: 3-6. tiktok.caption: one or two lines, at most 150 characters. tiktok.hashtags: 3-5. '
            'Hashtags start with # and contain no spaces.\n\n'
            f'Working title: {video_title(job)}\n\nNarration:\n{text}')


def _clean(value, limit):
    return re.sub(r'[ \t]+', ' ', str(value or '')).strip()[:limit]


def _tags(values, limit, hashtag):
    result = []
    for value in values if isinstance(values, list) else []:
        tag = re.sub(r'\s+', '', str(value or '').strip().lstrip('#'))
        if not tag:
            continue
        tag = ('#' + tag if hashtag else tag)[:60]
        if tag.lower() not in {t.lower() for t in result}:
            result.append(tag)
    return result[:limit]


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Social copy must be a JSON object')
    youtube, facebook, tiktok = (data.get(k) if isinstance(data.get(k), dict) else {} for k in ('youtube', 'facebook', 'tiktok'))
    result = {
        'youtube': {'title': _clean(youtube.get('title'), 100), 'description': _clean(youtube.get('description'), 5000),
                    'tags': _tags(youtube.get('tags'), 15, False)},
        'facebook': {'caption': _clean(facebook.get('caption'), 5000), 'hashtags': _tags(facebook.get('hashtags'), 8, True)},
        'tiktok': {'caption': _clean(tiktok.get('caption'), 300), 'hashtags': _tags(tiktok.get('hashtags'), 6, True)},
    }
    if not result['youtube']['title'] or not result['facebook']['caption'] or not result['tiktok']['caption']:
        raise ValueError('Social copy is missing a title or caption')
    return result


def path(job):
    return Path(job['output']) / FILE


def read(job):
    target = path(job)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return None


def _write(job, value):
    target = path(job)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    part.replace(target)
    return value


def generate(ask, job):
    """ask(prompt) returns the provider's JSON. Errors are stored, never raised."""
    if not narration(job):
        return _write(job, {'state': 'error', 'error': 'Video chưa có lời đọc', 'updated': time.time()})
    try:
        copy = validate(ask(prompt(job)))
        return _write(job, {'state': 'ready', **copy, 'updated': time.time()})
    except Exception as error:  # Best effort: the video itself is already finished.
        if type(error).__name__ == 'Cancelled':
            raise
        return _write(job, {'state': 'error', 'error': str(error)[:500], 'updated': time.time()})


def start(ask, job):
    """Write copy in the background. Returns False when it is already running."""
    with _lock:
        if job['id'] in _running:
            return False
        _running.add(job['id'])
    _write(job, {**(read(job) or {}), 'state': 'running', 'updated': time.time()})

    def run():
        try:
            generate(ask, job)
        finally:
            with _lock:
                _running.discard(job['id'])
    threading.Thread(target=run, name='social-copy-' + job['id'][:8], daemon=True).start()
    return True


def name_prompt(content):
    text = str(content or '').strip()
    if len(text) > 6000:
        text = text[:6000] + ' …'
    return ('Give this Vietnamese video a short Vietnamese title of at most 70 characters, written like a gripping true-crime or '
            'documentary headline: dramatic and curiosity-driven, built on the most shocking or mysterious real detail, teasing the twist '
            'without revealing the ending. No invented facts, no emoji, no quotation marks. ' + NO_HEDGING +
            'Return JSON exactly {"title":str}.\n\nContent:\n' + text)


def ask_name(ask, content):
    data = ask(name_prompt(content))
    title = data.get('title') if isinstance(data, dict) else None
    if not isinstance(title, str) or not title.strip():
        raise ValueError('AI did not return a title')
    return title.strip()[:100]
