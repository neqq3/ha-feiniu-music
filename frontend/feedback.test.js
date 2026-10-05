import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {FeiNiuMusicCard} from './feiniu-music-card.js';

const keys=['settings','feedbackMode','standardMode','compatibilityMode','feedbackHelp','estimateEnd','estimateHelp','endFeedback','endUnconfirmed','endFallback','confirmationHelp','awaitingFeedback','assumedFeedback','pauseRequested','resumeRequested','late_confirmed','estimated_end','durationUnknown','seekUnconfirmed'];
test('feedback labels exist distinctly in both card languages',()=>{
 for(const key of keys){
  const en=FeiNiuMusicCard.prototype.t.call({_hass:{language:'en'}},key);
  const zh=FeiNiuMusicCard.prototype.t.call({_hass:{language:'zh-Hans'}},key);
  assert.notEqual(en,key);assert.notEqual(zh,key);assert.notEqual(en,zh);
 }
});
test('feedback message distinguishes assumptions, requests and confirmed playback',()=>{
 const attrs={effective_feedback_mode:'compatibility',session_phase:'playing',confirmation_stage:'assumed',position_source:'estimated'};
 const subject={_attrs:attrs,t:key=>key};
 const message=()=>FeiNiuMusicCard.prototype._feedbackMessage.call(subject);
 assert.equal(message(),'assumedFeedback · estimated');
 attrs.session_reason='pause_requested';assert.equal(message(),'pauseRequested · estimated');
 attrs.session_reason='late_confirmed';attrs.confirmation_stage='confirmed';attrs.position_source='native';assert.equal(message(),'late_confirmed');
 attrs.session_phase='failed';assert.equal(message(),'');
 attrs.session_phase='playing';attrs.effective_feedback_mode='standard';assert.equal(message(),'');
});
test('native language keys match and confirmation help retains AND semantics',async()=>{
 const root=new URL('../custom_components/feiniu_music/',import.meta.url);
 const [source,en,zh]=await Promise.all(['strings.json','translations/en.json','translations/zh-Hans.json'].map(async file=>JSON.parse(await readFile(new URL(file,root),'utf8'))));
 const paths=(value,prefix='')=>Object.entries(value).flatMap(([key,item])=>typeof item==='object'?paths(item,`${prefix}${key}.`):[`${prefix}${key}`]).sort();
 assert.deepEqual(source,en);assert.deepEqual(paths(en),paths(zh));
 assert.match(en.options.step.playback_profile.data_description.confirmation,/association and a playing report/);
 assert.match(zh.options.step.playback_profile.data_description.confirmation,/关联检查和输出报告/);
 assert.match(en.options.step.unconfirmed_end.description,/5 seconds/);
 assert.match(zh.options.step.unconfirmed_end.description,/5 秒/);
});
