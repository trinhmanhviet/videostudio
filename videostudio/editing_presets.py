"""Deterministic, local editing defaults; these never generate media or narration."""
import copy

PRESETS = {
    'documentary': {'id': 'documentary', 'name': 'Documentary', 'description': 'Warm labels, slow camera movement and sparse chapter accents',
                    'motion': {'type': 'zoom_in', 'amount': .06}, 'transition': {'type': 'fade', 'duration': .35},
                    'label': {'color': '#FFF2D5', 'background': '#312A20', 'size': 48},
                    'captions': {'enabled': True, 'font_size': 52, 'color': '#FFFFFF', 'accent_color': '#EBC785', 'bottom_margin': 576, 'emphasis': []}},
    'science': {'id': 'science', 'name': 'Science', 'description': 'Cool clean labels, clear text emphasis and light chimes',
                'motion': {'type': 'pan_right', 'amount': .04}, 'transition': {'type': 'dissolve', 'duration': .25},
                'label': {'color': '#D7F4FF', 'background': '#112D40', 'size': 46},
                'captions': {'enabled': True, 'font_size': 50, 'color': '#F2FAFF', 'accent_color': '#72D5FF', 'bottom_margin': 576, 'emphasis': []}},
    'everyday': {'id': 'everyday', 'name': 'Everyday', 'description': 'Warm clear type and gentle movement',
                 'motion': {'type': 'zoom_out', 'amount': .035}, 'transition': {'type': 'fade', 'duration': .3},
                 'label': {'color': '#FFF7ED', 'background': '#413027', 'size': 50},
                 'captions': {'enabled': True, 'font_size': 52, 'color': '#FFFFFF', 'accent_color': '#FFCA9D', 'bottom_margin': 576, 'emphasis': []}},
}


def editing_presets():
    return copy.deepcopy(list(PRESETS.values()))


def get_preset(preset_id, *, fallback=False):
    if not isinstance(preset_id, str) or preset_id not in PRESETS:
        if not fallback: raise ValueError('Unknown editing preset')
        preset_id = 'documentary'
    return copy.deepcopy(PRESETS[preset_id])


def apply_preset(plan, preset_id):
    preset = get_preset(preset_id)
    result = copy.deepcopy(plan)
    result['preset_id'] = preset_id
    result['captions'] = preset['captions']
    for clip in result['clips']:
        if clip['kind'] in ('image', 'video'):
            clip['motion'] = copy.deepcopy(preset['motion'])
            clip['transition'] = copy.deepcopy(preset['transition'])
            clip['transition']['duration'] = min(clip['transition']['duration'], clip['end'] - clip['start'])
        elif clip['kind'] == 'text':
            clip.update(preset['label'])
    for event in result.get('sfx', []):
        if event['id'].startswith('sfx-accent-'):
            name = {'documentary': 'whoosh', 'science': 'chime', 'everyday': 'click'}[preset_id]
            length = {'whoosh': .65, 'chime': .9, 'click': .12}[name]
            event['asset_id'] = 'sfx-' + name
            event['end'] = min(result['duration'], event['start'] + length)
            event['fade_in'] = min(event.get('fade_in', 0), event['end']-event['start'])
            event['fade_out'] = min(event.get('fade_out', 0), event['end']-event['start'])
    return result
