import re
from pathlib import Path
from collections import Counter

output_dir = Path(r'D:\Projects\videostudio\data\facebook_cases\dem-nay-lai-co-chuyen')
md_files = [f for f in output_dir.glob('*.md') if f.name != 'README.md']

candidates = Counter()
for f in md_files:
    txt = f.read_text(encoding='utf-8')
    words = re.findall(r'\b[a-z]{4,20}\b', txt.lower())
    for w in words:
        candidates[w] += 1

# Let's inspect words that have >= 2 occurrences and look like compound vietnamese without diacritics
# E.g. contains subwords like giet, sat, chet, mang, thi, xac, dam, chem, bop, siet, danh, bat, cuop, hiep, v.v.
keywords = ['giet', 'sat', 'chet', 'mang', 'thi', 'xac', 'dam', 'chem', 'bop', 'siet', 'danh', 'bat', 'cuop', 'hiep', 'tu', 'bao', 'nan', 'an', 'hinh', 'toi', 'pham', 'doc', 'tang', 'tich', 'vong', 'mau', 'hoa', 'troi', 'trom', 'giau', 'hon', 'tai', 'khoa', 'than', 'xung', 'kiem', 'tra', 'tham', 'van', 'truy', 'na']

matched = {}
for w, c in candidates.items():
    if any(k in w for k in keywords):
        matched[w] = c

with open(str(Path(__file__).resolve().parents[3]/'data/facebook_cases/scratch/scratch_compound_evasions.txt'), 'w', encoding='utf-8') as out:
    for w, c in sorted(matched.items(), key=lambda x: -x[1]):
        out.write(f"{w}: {c}\n")

print(f"Found {len(matched)} candidate compound evasion words.")
