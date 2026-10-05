// Real shipped component, on both Chromium and WebKit, with synthetic HA states.
import assert from 'node:assert/strict';

export async function checkFeedback(browser,url){
 const page=await browser.newPage({viewport:{width:1280,height:850}});
 page.setDefaultTimeout(5000);
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(url);
  const card=page.locator('feiniu-music-card').first();
  await card.locator('.tile').first().waitFor();
  for(const language of ['zh-Hans','en']){
   await page.evaluate(language=>{hass.language=language;document.querySelector('feiniu-music-card').hass=hass;},language);
   await card.getByRole('button',{name:language==='en'?'Playback feedback and continuation':'播放反馈与续播',exact:true}).click();
   assert.equal(await card.locator('#feedback-mode').inputValue(),'standard');
   assert.equal(await card.locator('#estimated-end').isVisible(),false);
   assert.match(await card.locator('#confirmation').textContent(),language==='en'?/Playing report plus audio delivery/:/播放中反馈，并有音频传输/);
   await card.locator('#feedback-mode').selectOption('compatibility');
   assert.equal(await card.locator('#estimated-end').isVisible(),true);
   assert.equal(await card.locator('#estimated-end').isChecked(),false);
   await card.locator('#estimated-end').check();
   await card.locator('#save-preferences button').click();
   assert.deepEqual(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).profile),{feedback_mode:'compatibility',unconfirmed_end:'estimated_duration'});
  }
  await page.evaluate(()=>{
   const c=document.querySelector('feiniu-music-card');
   hass.language='zh-Hans';
   Object.assign(hass.states['media_player.feiniu_a'].attributes,{effective_feedback_mode:'compatibility',effective_unconfirmed_end:'estimated_duration',confirmation_stage:'assumed',position_source:'estimated',session_reason:'start_unconfirmed_retained'});
   c.setConfig({entity:'media_player.feiniu_a',display_mode:'compact',compact_view:'lyrics'});c.hass=hass;
  });
  await card.locator('.lyric-seek').first().waitFor({state:'attached'});
  for(const width of [390,1280]){
   await page.setViewportSize({width,height:850});
   assert.match(await card.locator('#compact-status').textContent(),/播放未确认.*估算/);
   assert.equal(await card.locator('#seek').isDisabled(),true);
   assert.equal(await card.locator('.lyric-seek').first().isDisabled(),true);
   const before=await page.evaluate(()=>calls.filter(c=>c.service==='media_seek').length);
   await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');return c._seekLyric(c._lyrics[0],c._lyricKey);});
   assert.equal(await page.evaluate(()=>calls.filter(c=>c.service==='media_seek').length),before);
  }
  await page.evaluate(()=>{const a=hass.states['media_player.feiniu_a'].attributes;a.session_reason='pause_requested';a.session_phase='paused';hass.states['media_player.feiniu_a'].state='paused';document.querySelector('feiniu-music-card').hass=hass;});
  assert.match(await card.locator('#compact-status').textContent(),/已请求暂停.*设备状态未确认/);
  await page.evaluate(()=>{const a=hass.states['media_player.feiniu_a'].attributes;Object.assign(a,{confirmation_stage:'confirmed',position_source:'native',session_reason:'late_confirmed',session_phase:'playing'});hass.states['media_player.feiniu_a'].state='playing';document.querySelector('feiniu-music-card').hass=hass;});
  assert.equal(await card.locator('#seek').isDisabled(),false);
  assert.equal(await card.locator('.lyric-seek').first().isDisabled(),false);
  assert.match(await card.locator('#compact-status').textContent(),/已收到本轮播放反馈/);
  await page.evaluate(()=>{const a=hass.states['media_player.feiniu_a'].attributes;a.playback_profile={feedback_mode:'compatibility',unconfirmed_end:'estimated_duration'};document.querySelector('feiniu-music-card').hass=hass;});
  // Open the existing settings dialog through the actual compact expand interface.
  await page.evaluate(()=>document.querySelector('feiniu-music-card')._preferences());
  await card.locator('#feedback-mode').selectOption('standard');
  assert.equal(await card.locator('#estimated-end').isVisible(),false);
  await card.locator('#save-preferences button').click();
  assert.deepEqual(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).profile),{feedback_mode:'standard',unconfirmed_end:'manual'});
  assert.deepEqual(errors,[]);
  console.log('Feedback DOM checks passed: bilingual settings, conditional estimate opt-in, truthful statuses, seek/lyric gating and late confirmation at 390/1280px.');
 }finally{await page.close();}
}
