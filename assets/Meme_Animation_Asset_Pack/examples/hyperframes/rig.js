export function createRig(root, spec) {
  const nodes = new Map();
  for (const layer of [...spec.layers].sort((a,b)=>(a.z??0)-(b.z??0))) {
    const img = document.createElement('img');
    img.src = layer.asset;
    img.dataset.layerId = layer.id;
    Object.assign(img.style, {
      position:'absolute', inset:'0', width:'100%', height:'100%', objectFit:'contain',
      transformOrigin:`${(layer.anchor?.[0]??0.5)*100}% ${(layer.anchor?.[1]??0.5)*100}%`,
      pointerEvents:'none'
    });
    root.appendChild(img); nodes.set(layer.id,img);
  }
  return {
    node:id=>nodes.get(id),
    swap(id,src){ const n=nodes.get(id); if(n) n.src=src; },
    show(id,on=true){ const n=nodes.get(id); if(n) n.style.display=on?'block':'none'; }
  };
}

export function addTalkCycle(tl, rig, mouthAssets, start, duration, step=.10){
  const mouth=rig.node('mouth');
  if(!mouth || !mouthAssets.length) return;
  const count=Math.ceil(duration/step);
  for(let i=0;i<count;i++){
    const src=mouthAssets[i%mouthAssets.length];
    tl.call(()=>{mouth.src=src},[],start+i*step);
  }
}
