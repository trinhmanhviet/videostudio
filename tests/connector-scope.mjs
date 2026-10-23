import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studioScope,sameScope} from 'file:///D:/Projects/storyforge/extensions/chatgpt-web/protocol.js';
const id='11111111-1111-4111-8111-111111111111',run='22222222-2222-4222-8222-222222222222';
const scope={project_id:id,run_id:run,studio_tab_id:7,studio_origin:'http://127.0.0.1:8877'};
const sender={tab:{id:7},frameId:0,url:`http://127.0.0.1:8877/story-video/projects/${id}/production`};
test('VideoStudio exact origin and production route permitted',()=>assert.equal(studioScope(sender,scope),true));
test('Other port, root page, frame and changed tab rejected',()=>{
 for(const altered of [{...sender,url:sender.url.replace(':8877',':8878')},{...sender,url:'http://127.0.0.1:8877/'},{...sender,frameId:1},{...sender,tab:{id:8}}])assert.equal(studioScope(altered,scope),false);
});
test('VideoStudio never aliases original StoryForge origin',()=>assert.equal(sameScope(scope,{...scope,studio_origin:'http://127.0.0.1:3000'}),false));
