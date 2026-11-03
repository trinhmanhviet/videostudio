import test from 'node:test';
import assert from 'node:assert/strict';
import {EditorPreview} from '../static/editor-preview.mjs';

test('preview matches export pan direction and caption canvas scaling and pauses inactive video',()=>{
  class Video {pause(){this.paused=true;}removeAttribute(){}load(){}}
  globalThis.HTMLVideoElement=Video;
  const draws=[],labels=[],context=new Proxy({drawImage(...args){draws.push(args);}}, {get:(obj,key)=>obj[key]??(()=>{})});
  const preview=new EditorPreview({width:540,height:960,getContext:()=>context});
  preview.plan={duration:10,canvas:{width:540,height:960,fps:30},tracks:[{id:'v',kind:'image'}],clips:[{id:'a',asset_id:'a',kind:'image',track_id:'v',start:0,end:10,motion:{type:'pan_right',amount:.1}}],captions:{font_size:52,bottom_margin:576}};
  preview.assets={a:{id:'a',kind:'image'}};preview.cues=[{start:0,end:10,text:'Caption'}];
  preview.element=()=>({naturalWidth:540,naturalHeight:960});preview.text=(...args)=>labels.push(args);
  const inactive=new Video();preview.media.set('video:old',{element:inactive});
  for(let i=0;i<40;i++)preview.media.set('image:'+i,{element:{}});
  preview.time=0;preview.draw();const first=draws[0][5];preview.time=9;preview.draw();
  assert.ok(draws[1][5]<first,'pan right moves the crop to the right, like FFmpeg');
  assert.equal(labels[0][3],26);assert.equal(labels[0][2],960-288-26*.35);
  assert.equal(inactive.paused,true);
  assert.ok(preview.media.size<=32);assert.equal(preview.media.has('video:old'),false);
  delete globalThis.HTMLVideoElement;
});
