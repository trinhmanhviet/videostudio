from pathlib import Path
import json

p = Path('data/flow-images/batches/aa9d2bad-5936-5dda-ad08-a1426abda45f.json')
data = json.loads(p.read_text(encoding='utf-8'))
for t in data.get('tasks', []):
    print(json.dumps(t, ensure_ascii=True))
