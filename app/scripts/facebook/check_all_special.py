import re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

p = Path(r'D:\Projects\videostudio\data\facebook_cases\dem-nay-lai-co-chuyen')
md_files = [f for f in p.glob('*.md') if f.name != 'README.md']

# Check all words that have unusual slash or asterisk or unaccented crime patterns
patterns = set()
for f in md_files:
    txt = f.read_text(encoding='utf-8')
    # Words with slash
    for w in re.findall(r'\b\w*(?:/\w+)+\b', txt):
        if not re.match(r'^\d+(?:/\d+)+$', w):
            patterns.add(('slash', w))
    # Words with asterisk
    for w in re.findall(r'\b\w*\*+\w*\b', txt):
        patterns.add(('asterisk', w))

print("Total special patterns:", len(patterns))
with open(str(Path(__file__).resolve().parents[3]/'data/facebook_cases/scratch/scratch_all_special.txt'), 'w', encoding='utf-8') as out:
    for t, w in sorted(patterns):
        out.write(f"[{t}] {w}\n")
