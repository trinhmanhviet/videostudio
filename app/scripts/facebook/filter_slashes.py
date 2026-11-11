import re
from pathlib import Path

txt = Path(str(Path(__file__).resolve().parents[3]/'data/facebook_cases/scratch/scratch_patterns.txt')).read_text(encoding='utf-8')
slashes = [l.strip() for l in txt.split('=== SLASH WORDS ===')[1].split('=== UNACCENTED WORDS ===')[0].splitlines() if l.strip()]
non_dates = [s for s in slashes if not re.match(r'^\d+(?:/\d+)+$', s)]

Path(str(Path(__file__).resolve().parents[3]/'data/facebook_cases/scratch/scratch_non_date_slashes.txt')).write_text('\n'.join(non_dates), encoding='utf-8')
print(f'Wrote {len(non_dates)} non-date slash words.')
