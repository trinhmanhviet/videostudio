import re, sys
from pathlib import Path

output_dir = Path(r'D:\Projects\videostudio\data\facebook_cases\dem-nay-lai-co-chuyen')
md_files = [f for f in output_dir.glob('*.md') if f.name != 'README.md']

asterisk_words = set()
slash_words = set()
unaccented_evasions = set()

# Regex to find words with * or /
re_asterisk = re.compile(r'\b\w*\*+\w*\b', re.UNICODE)
re_slash = re.compile(r'\b\w+(?:/+\w+)+\b', re.UNICODE)

known_unaccented = ['sathai', 'tutu', 'anmang', 'gietnguoi', 'thithe', 'phitang', 'lamdung', 'mattich', 'tuvong', 'danhdap', 'cuonghiep', 'uchiep', 'xammhai', 'cuongsat', 'toipham', 'xathit']

found_unaccented = {w: 0 for w in known_unaccented}

for f in md_files:
    txt = f.read_text(encoding='utf-8')
    for m in re_asterisk.findall(txt):
        if len(m) > 1 and '*' in m:
            asterisk_words.add(m)
    for m in re_slash.findall(txt):
        if '/' in m and len(m) > 2:
            slash_words.add(m)
    txt_lower = txt.lower()
    for w in known_unaccented:
        if w in txt_lower:
            found_unaccented[w] += 1

with open(str(Path(__file__).resolve().parents[3]/'data/facebook_cases/scratch/scratch_patterns.txt'), 'w', encoding='utf-8') as out:
    out.write("=== ASTERISK WORDS ===\n")
    out.write('\n'.join(sorted(asterisk_words)) + '\n\n')
    out.write("=== SLASH WORDS ===\n")
    out.write('\n'.join(sorted(slash_words)) + '\n\n')
    out.write("=== UNACCENTED WORDS ===\n")
    for k, v in found_unaccented.items():
        out.write(f"{k}: {v}\n")

print(f"Scanned {len(md_files)} files. Asterisks: {len(asterisk_words)}, Slashes: {len(slash_words)}")
