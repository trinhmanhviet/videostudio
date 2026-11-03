import test from 'node:test';
import assert from 'node:assert/strict';
import {findClip, moveClip, trimClip, splitClip, removeClip, PlanHistory, formatTime,activeVisualClips,transitionOpacity,addClip,moveTrack,videoSourceTime} from '../static/editor-model.mjs';

const fixture=()=>({duration:12,tracks:[{id:'visual',kind:'image',locked:false},{id:'voice',kind:'narration',locked:true},{id:'music',kind:'music',locked:false}],
  clips:[{id:'image-1',kind:'image',track_id:'visual',scene_id:'scene-0',start:0,end:6,asset_id:'image-a'},
         {id:'video-2',kind:'video',track_id:'visual',scene_id:'scene-1',start:6,end:12,source_start:2,asset_id:'video-b'},
         {id:'voice',kind:'audio',track_id:'voice',start:0,end:12,asset_id:'speech'}],
  music:[{id:'music-a',kind:'audio',track_id:'music',start:0,end:12,source_start:0,asset_id:'music'}],sfx:[]});

test('dissolve preview holds the old frame beneath an incoming fade without a dark exit',()=>{
  const plan=fixture();plan.clips=plan.clips.slice(0,2);plan.clips[1].transition={type:'dissolve',duration:1};
  assert.deepEqual(activeVisualClips(plan,6.5).map(c=>c.id),['image-1','video-2']);
  assert.equal(transitionOpacity({...plan.clips[1],end:7},6.5),.5);
  assert.ok(Math.abs(transitionOpacity({...plan.clips[1],end:7},6.9)-.9)<1e-9);
});
test('a trimmed video freezes its final frame during the outgoing dissolve hold',()=>{
  const clip={start:3,end:4,source_start:2};
  assert.equal(videoSourceTime(clip,3.5,30),2.5);
  assert.equal(videoSourceTime(clip,4.5,30),2+29/30);
});
test('short clips and split audio keep fades inside their new duration',()=>{
  const plan=fixture();plan.clips[0].transition={type:'fade',duration:1};plan.music[0].fade_out=2;
  const trimmed=trimClip(plan,'image-1','right',.2);assert.ok(trimmed.clips[0].transition.duration<=.1);
  const split=splitClip(plan,'music-a',.2,'short-audio');assert.ok(split.music[0].fade_out<=.2);
  const added=addClip(plan,{id:'tail-title',track_id:'visual',kind:'text',start:11.9,end:12,text:'End',transition:{type:'fade',duration:.25}});
  assert.ok(findClip(added,'tail-title').clip.transition.duration<=.051);
});
test('layer ordering changes the visual stack without moving narration or rewriting clips',()=>{
  const plan=fixture();plan.tracks.push({id:'titles',kind:'text',locked:false});
  const moved=moveTrack(plan,'visual',1);
  assert.ok(moved.tracks.findIndex(t=>t.id==='visual')>moved.tracks.findIndex(t=>t.id==='titles'));
  assert.deepEqual(moved.clips,plan.clips);assert.equal(plan.tracks[0].id,'visual');
});

test('moving a clip preserves its source and duration and clamps within measured narration',()=>{
  const original=fixture(),changed=moveClip(original,'image-1',10);
  assert.deepEqual([findClip(changed,'image-1').clip.start,findClip(changed,'image-1').clip.end],[6,12]);
  assert.equal(original.clips[0].start,0);
  assert.equal(changed.clips[0].asset_id,'image-a');
});
test('left trim advances real video source time and cannot extend before source zero',()=>{
  const changed=trimClip(fixture(),'video-2','left',4);
  assert.equal(changed.clips[1].start,4);assert.equal(changed.clips[1].source_start,0);
  const extended=trimClip(changed,'video-2','left',0);
  assert.equal(extended.clips[1].start,4);
});
test('right trim uses source duration, not merely the visual timeline',()=>{
  const original=fixture();original.clips[1].end=9;
  const changed=trimClip(original,'video-2','right',12,{'video-b':{duration:5}});
  assert.equal(changed.clips[1].end,9);
});
test('split preserves scene and effect metadata and offsets video source for the right piece',()=>{
  const original=fixture();original.clips[1].motion={type:'pan_left',amount:.1};
  const changed=splitClip(original,'video-2',8,'video-right');
  const right=findClip(changed,'video-right').clip;
  assert.equal(right.source_start,4);assert.equal(right.scene_id,'scene-1');assert.deepEqual(right.motion,{type:'pan_left',amount:.1});
  assert.equal(findClip(changed,'video-2').clip.end,8);assert.equal(original.clips[1].end,12);
});
test('locked narration timing cannot be moved, split, or removed',()=>{
  for(const change of [()=>moveClip(fixture(),'voice',1),()=>splitClip(fixture(),'voice',3,'other'),()=>removeClip(fixture(),'voice')])assert.throws(change,/khóa|locked/i);
});
test('music edits apply to the correct collection without changing source narration',()=>{
  const changed=splitClip(fixture(),'music-a',5,'music-right');
  assert.equal(changed.music.length,2);assert.equal(changed.clips.length,3);
  assert.equal(findClip(changed,'music-right').clip.source_start,5);
  assert.equal(removeClip(changed,'music-right').music.length,1);
});
test('undo/redo saves complete plans and a new edit clears the redo branch',()=>{
  const original=fixture(),history=new PlanHistory(original);
  history.push(moveClip(original,'image-1',1));assert.equal(history.current.clips[0].start,1);
  assert.equal(history.undo().clips[0].start,0);assert.equal(history.redo().clips[0].start,1);
  history.undo();history.push(moveClip(original,'image-1',2));assert.equal(history.canRedo,false);
  assert.equal(original.clips[0].start,0);
});
test('display time handles hours and non-finite input without breaking the timeline',()=>{
  assert.equal(formatTime(3661.5),'01:01:01.500');assert.equal(formatTime(NaN),'00:00.000');
});
