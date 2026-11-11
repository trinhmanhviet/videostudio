"""Fill page-script templates without letting page text collide with placeholders."""
import json


def fill_card_template(template, index, text, x=None, y=None):
    """Numeric placeholders first, page text last: card text may contain INDEX, X) or Y)."""
    script = template.replace('INDEX', str(int(index)))
    if x is not None:
        script = script.replace('X)', str(x) + ')')
    if y is not None:
        script = script.replace('Y)', str(y) + ')')
    return script.replace('TEXT', json.dumps(text, ensure_ascii=False))
