"""Stage dispatch for the single meme story and HyperFrames production pipeline."""
from __future__ import annotations

import json

MODE = 'meme'


def is_meme(job):
    return job.get('request',{}).get('workflow_mode') == MODE


def _log(pipeline, job, stage, text):
    store = getattr(pipeline,'store',None)
    if store:store.log(job['id'],stage,text)


def _save(path, value):
    part = path.with_suffix(path.suffix+'.part')
    part.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    part.replace(path)


def plan(pipeline,job,check):
    from . import meme_animation
    return meme_animation.plan(pipeline,job,check)


def research(pipeline,job,check):
    check()
    return {'sources':[],'assets':[],'mode':'meme_no_research','provenance':'meme_story','context':{},'factual_claims_permitted':False}


def script(pipeline,job,check):
    from . import meme_animation
    return meme_animation.script(pipeline,job,check)


def images(pipeline,job,check):
    from . import meme_animation
    return meme_animation.images(pipeline,job,check)


def render(pipeline,job,check):
    from . import meme_animation
    return meme_animation.render(pipeline,job,check)


def verify(pipeline,job,check):
    from . import meme_animation
    return meme_animation.verify(pipeline,job,check)
