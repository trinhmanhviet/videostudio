"""app/ holds the code; everything the tool writes lives in data/, next to it."""
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.getenv('VS_DATA_ROOT', str(APP_ROOT.parent / 'data')))
RUNTIME_ROOT = DATA_ROOT / 'runtime'
VOICE_ROOT = Path(os.getenv('VS_VOICE_ROOT', str(DATA_ROOT)))
