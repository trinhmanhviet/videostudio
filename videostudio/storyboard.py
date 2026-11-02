"""Visual scene boundaries are independent of caption-safe narration chunks."""
import unicodedata


VISUAL_GROUPING_VERSION = 1
VISUAL_GROUPING_RULES = (
    'VISUAL SCENE GROUPING: Decide image boundaries by story content, not caption length. '
    'Keep related narration in ONE visual scene while the visible subject, location, time and action remain coherent. '
    'Start a new scene when the location, time, main visible subject or depicted action changes. '
    'Use as many narration sentences as the content needs; do not enforce a fixed sentence count per image. '
    'Return the complete scene narration and its narration_lines in the original spoken order. '
    'Do not shorten or omit narration to fit subtitles: the tool splits caption-safe lines locally. '
    'Give each scene one English visual_prompt (camera, subject, environment, lighting) and an instrumental music_prompt. '
)


def grouping_enabled(job):
    return job.get('checkpoints', {}).get('plan', {}).get('visual_grouping_version') == VISUAL_GROUPING_VERSION


def normalize_visual_scenes(scenes, split_lines, *, start_index=0, music_prompt='instrumental', preserve_ids=False):
    """Repair optional line metadata locally, treating full narration as authoritative."""
    result = []
    for index, original in enumerate(scenes, start_index):
        if not isinstance(original, dict) or not isinstance(original.get('visual_prompt'), str) or not original['visual_prompt'].strip():
            raise ValueError('Missing scene visual prompt')
        scene = dict(original)
        raw_lines = scene.get('narration_lines')
        valid_lines = isinstance(raw_lines, list) and bool(raw_lines) and all(isinstance(line, str) and line.strip() for line in raw_lines)
        narration = scene.get('narration')
        if not isinstance(narration, str) or not narration.strip():
            narration = ' '.join(raw_lines) if valid_lines else ''
        canonical = lambda text: ' '.join(unicodedata.normalize('NFC', text).split())
        # Missing, reordered, invented or truncated lines must not change spoken text.
        if not valid_lines or canonical(' '.join(raw_lines)) != canonical(narration):
            raw_lines = [narration]
        lines = [chunk for line in raw_lines for chunk in split_lines(line)]
        if not lines:
            raise ValueError('Missing scene narration')
        scene['narration_lines'] = lines
        scene['narration'] = ' '.join(lines)
        if not preserve_ids or not scene.get('scene_id'):
            scene['scene_id'] = f'scene-{index:04}'
        if not scene.get('music_prompt'):
            scene['music_prompt'] = music_prompt
        result.append(scene)
    return result


def group_supplied_scenes(scenes, split_lines, *, music_prompt='instrumental'):
    """Only explicit adjacent, visually identical line groups may share an image."""
    groups = []
    previous_key = None
    for original in scenes:
        scene = dict(original)
        label = scene.pop('visual_group_id', None)
        label = label.strip() if isinstance(label, str) and 0 < len(label.strip()) <= 80 else None
        key = (label, scene['visual_prompt'], tuple(sorted(scene.get('character_ids', [])))) if label else None
        if groups and key is not None and key == previous_key:
            group = groups[-1]
            group['narration'] += ' ' + scene['narration']
            group['narration_lines'].append(scene['narration'])
            group['source_line_ids'].append(scene['scene_id'])
        else:
            scene['narration_lines'] = [scene['narration']]
            scene['source_line_ids'] = [scene['scene_id']]
            groups.append(scene)
        previous_key = key
    return normalize_visual_scenes(groups, split_lines, music_prompt=music_prompt, preserve_ids=True)
