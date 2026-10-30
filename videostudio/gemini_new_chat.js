(()=>{
  const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
  const norm=s=>String(s||'').normalize('NFC').trim().toLocaleLowerCase();
  const clean=s=>norm(s).replace(/\s*ctrl\+shift\+o$/i,'').trim();
  const labels=new Set([
    'new chat',
    '\u0063\u0075\u1ed9\u0063 \u0074\u0072\u00f2 \u0063\u0068\u0075\u0079\u1ec7\u006e \u006d\u1edb\u0069',
    '\u0074\u1ea1\u006f \u0063\u0075\u1ed9\u0063 \u0074\u0072\u00f2 \u0063\u0068\u0075\u0079\u1ec7\u006e \u006d\u1edb\u0069',
  ]);
  const candidates=[...document.querySelectorAll('a.mat-mdc-list-item,button.mat-mdc-list-item')]
    .filter(vis)
    .filter(e=>{
      const text=clean(e.innerText),label=clean(e.getAttribute('aria-label'));
      return labels.has(text)&&(!label||labels.has(label));
    });
  if(candidates.length!==1)return false;
  const hit=candidates[0],r=hit.getBoundingClientRect();
  const under=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
  if(!under||!(under===hit||hit.contains(under)))return false;
  hit.click();
  return true;
})()
