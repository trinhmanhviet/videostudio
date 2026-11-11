import sys, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

p = (Path(__file__).resolve().parents[3]/'data/facebook_cases/clean_txt')
files = sorted([f for f in p.glob('*.txt') if f.name not in ('INDEX.txt', 'all_cases_clean.txt')])

results = []
for f in files:
    content = f.read_text(encoding='utf-8')
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    first_few = ' '.join(lines[:3]) if lines else ''
    
    # Check filename
    fn_m = re.search(r'[-_](?:phan|ky|tap|part)[-_]?(\d+|cuoi|ket)\b', f.name, re.IGNORECASE)
    
    # Check text
    txt_m = re.search(r'\b(?:phần|kỳ|tập|part)\s*(\d+|cuối|kết|hồi kết|đầu|\bI\b|\bII\b|\bIII\b|\bIV\b|\bV\b)\b', first_few, re.IGNORECASE)
    
    # Check brackets
    bracket_m = re.search(r'\(([0-9]+)\)\s*$', lines[0] if lines else '')
    
    tag = None
    part_val = None
    source = None
    if txt_m:
        tag = txt_m.group(0)
        part_val = txt_m.group(1).lower()
        source = 'text'
    elif fn_m:
        tag = fn_m.group(0)
        part_val = fn_m.group(1).lower()
        source = 'filename'
    elif bracket_m:
        tag = bracket_m.group(0)
        part_val = bracket_m.group(1)
        source = 'bracket'
        
    if tag:
        results.append((f.name, lines[0] if lines else '', tag, part_val, source))

print(f"Total found: {len(results)}")
for fn, title, tag, p_val, src in results:
    print(f"{fn:55} | src: {src:8} | tag: {tag:15} | val: {p_val:5} | {title[:50]}")
