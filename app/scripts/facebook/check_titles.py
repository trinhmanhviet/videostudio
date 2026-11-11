from pathlib import Path

SRC_DIR = Path(r'D:\Projects\videostudio\data\facebook_cases\clean_txt')
idx_text = (SRC_DIR / 'INDEX.txt').read_text(encoding='utf-8')
long_titles = []
for l in idx_text.splitlines():
    if l.startswith(('0', '1', '2')) and '[' in l:
        t = l.split('[')[0].strip()
        if len(t) > 75:
            long_titles.append((len(t), t[:120]))

with open(str(Path(__file__).resolve().parents[3]/'data/facebook_cases/scratch/scratch_long_titles.txt'), 'w', encoding='utf-8') as out:
    for length, t in long_titles:
        out.write(f"[{length}] {t}\n")
