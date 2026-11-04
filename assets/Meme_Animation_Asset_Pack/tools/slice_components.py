from pathlib import Path
from PIL import Image
import argparse, json
import cv2, numpy as np

def slice_components(src, out_dir, min_area=300, pad=6):
    src=Path(src); out=Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    im=Image.open(src).convert('RGBA')
    arr=np.array(im)
    alpha=arr[:,:,3]
    mask=(alpha>8).astype(np.uint8)
    n, labels, stats, cent = cv2.connectedComponentsWithStats(mask,8)
    rows=[]; idx=1
    for i in range(1,n):
        x,y,w,h,area=map(int,stats[i])
        if area < min_area: continue
        x0=max(0,x-pad); y0=max(0,y-pad); x1=min(im.width,x+w+pad); y1=min(im.height,y+h+pad)
        crop=im.crop((x0,y0,x1,y1))
        name=f'component_{idx:03d}.png'
        crop.save(out/name)
        rows.append({'file':name,'bbox':[x0,y0,x1,y1],'area':area,'centroid':[float(cent[i][0]),float(cent[i][1])]})
        idx+=1
    (out/'components.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{src.name}: {len(rows)} components -> {out}')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out_dir'); ap.add_argument('--min-area',type=int,default=300); ap.add_argument('--pad',type=int,default=6)
    a=ap.parse_args(); slice_components(a.src,a.out_dir,a.min_area,a.pad)
