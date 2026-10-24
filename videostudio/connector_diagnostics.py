"""Bounded connector diagnostics. Status never grants send authorization."""
import math,re

def redact(value,limit=600):
    value=str(value)[:3000]
    value=re.sub(r'(?i)Bearer\s+[^\s,;]+','Bearer [REDACTED]',value)
    value=re.sub(r'(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[:=]\s*)[^\s,;&]+',r'\1[REDACTED]',value)
    return value[:limit]

def sanitize_status(data):
    d={k:(redact(data[k],120) if isinstance(data[k],str) else data[k]) for k in ('build','stage','connected','enabled') if k in data and isinstance(data[k],(str,bool))}
    if isinstance(data.get('error'),dict):
        d['error']={k:redact(data['error'][k],100 if k=='code' else 600) for k in ('code','message') if isinstance(data['error'].get(k),str)}
    if isinstance(data.get('logs'),list):
        d['logs']=[]
        for row in data['logs'][-15:]:
            if not isinstance(row,dict):continue
            r={k:redact(row[k],100 if k=='code' else 600) for k in ('code','message') if isinstance(row.get(k),str)}
            if isinstance(row.get('at'),(int,float)) and math.isfinite(row['at']):r['at']=row['at']
            d['logs'].append(r)
    return d
