import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context=vm.createContext({URL});
vm.runInContext(fs.readFileSync(new URL('../static/video-folder.js',import.meta.url),'utf8'),context);
const target=value=>JSON.parse(JSON.stringify(context.VideoFolder.videoTarget(value,'http://localhost:8877/')));
test('folder action follows both output formats and the selected historical version',()=>{
  assert.deepEqual(target('/api/jobs/job-1/files/video.mp4?t=1'),{job_id:'job-1'});
  assert.deepEqual(target('/api/jobs/job-1/files/video-ngang.mp4'),{job_id:'job-1'});
  assert.deepEqual(target('/api/factory/videos/job-1/versions/old-version/file'),{job_id:'job-1',version_id:'old-version'});
  assert.equal(target('https://foreign.invalid/api/jobs/job-1/files/video.mp4'),null);
  assert.equal(target('/api/jobs/job-1/files/speech.wav'),null);
});
