// Additional interactions in the existing synthetic browser harness, without real outputs.
import assert from 'node:assert/strict';

export async function checkLyrics(page, first) {
  await page.setViewportSize({width:1280,height:960});
  await page.evaluate(()=>{
    const c=document.querySelector('feiniu-music-card');
    window.lyricTestState=structuredClone(hass.states[c._config.entity]);
    window.lyricTestLines=c._lyrics;
    // Reproduce the host style observed in HA 2026.9.4, absent from bare HTML.
    if(!customElements.get('ha-card'))customElements.define('ha-card',class extends HTMLElement{
      constructor(){super();this.attachShadow({mode:'open'}).innerHTML='<style>:host{transition:0.3s ease-out;display:block}</style><slot></slot>';}
    });
    const a=hass.states[c._config.entity];a.state='paused';
    Object.assign(a.attributes,{media_position:16,media_position_updated_at:new Date().toISOString(),lyric_offset:0});
    c.hass=hass;c._lyrics=Array.from({length:35},(_,i)=>({time_ms:i*4000,text:i===12?'<img src=x onerror="window.injected=true">':`A familiar song · ${i+1}`}));
    c._renderContent();c._animate();
  });
  assert.equal(await first.locator('#lyric-lines img').count(),0,'Lyric text cannot inject markup');
  assert.equal(await first.locator('#lyric-follow').count(),0,'No return-to-current button');
  assert.equal(await first.locator('#lyric-tools button').count(),3,'Two offset controls and their resettable value');
  const audioBefore=await page.evaluate(()=>calls.length);
  await first.locator('.now-art').hover();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-tools')).opacity==='0');
  await first.locator('.lyric-panel').hover();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-tools')).opacity==='1');
  await first.locator('.now-art').hover();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-tools')).opacity==='0');
  await first.locator('#lyricEarlier').focus();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-tools')).opacity==='1');
  await first.locator('#lyricEarlier').click();
  assert.deepEqual(await page.evaluate(()=>{const m=messages.filter(m=>m.type==='feiniu_music/preferences').at(-1);return [m.entity_id,m.lyric_offset,m.profile];}),['media_player.feiniu_a',.5,undefined]);
  await first.locator('#lyricEarlier').click();
  assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).lyric_offset),1,'Rapid subsequent actions retain saved offset before HA broadcasts it');
  await first.locator('#lyricLater').click();
  assert.equal(await first.locator('#lyric-offset-value').textContent(),'+0.5s');
  await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.lyric_offset=.5;c.hass=hass;});
  assert.equal(await first.locator('#lyric-offset-value').textContent(),'+0.5s','Backend offset and quick controls agree');
  assert.equal(await page.evaluate(()=>calls.length),audioBefore,'Offset changes never seek or control the audio');
  await page.evaluate(()=>{window.lyricOriginalWS=hass.callWS;hass.callWS=async m=>{if(m.type==='feiniu_music/preferences')throw new Error('synthetic preference rejection');return lyricOriginalWS(m);};});
  await first.locator('#lyricEarlier').click();
  assert.equal(await first.locator('#lyric-offset-value').textContent(),'+0.5s','A failed preference save rolls back the display offset');
  await page.evaluate(()=>{hass.callWS=lyricOriginalWS;const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.lyric_offset=30;c.hass=hass;});
  assert(await first.locator('#lyricEarlier').isDisabled(),'The existing 30-second maximum also applies to quick controls');
  await first.locator('#lyric-offset-value').click();
  assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).lyric_offset),0);
  await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.lyric_offset=.5;c.hass=hass;});
  assert.equal(await first.locator('#lyric-offset-value').textContent(),'+0.5s','External settings changes replace the preview value');
  const box=first.locator('#lyric-lines');
  await box.hover();await page.mouse.wheel(0,300);
  await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyricsManual);
  const manualTop=await box.evaluate(e=>e.scrollTop);
  await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.media_position=20;c.hass=hass;});
  assert(Math.abs(await box.evaluate(e=>e.scrollTop)-manualTop)<2,'New current line does not pull the user back during manual browsing');
  // Real elapsed inactivity, including one wheel action extending the deadline.
  await page.waitForTimeout(4200);await box.hover();await page.mouse.wheel(0,60);
  await page.waitForTimeout(4200);
  assert(await first.evaluate(c=>c._lyricsManual),'Continued scrolling restarts the inactivity timer');
  await page.waitForFunction(()=>!document.querySelector('feiniu-music-card')._lyricsManual,{},{timeout:6000});
  await page.waitForFunction(()=>{const c=document.querySelector('feiniu-music-card'),box=c.shadowRoot.querySelector('#lyric-lines'),row=box.querySelector('.current');return Math.abs(row.getBoundingClientRect().top+row.clientHeight/2-box.getBoundingClientRect().top-box.clientHeight/2)<2;});
  const centreOnlyBefore=await page.evaluate(()=>calls.length);
  await first.locator('.lyric-row p').nth(8).click();
  await page.waitForFunction(()=>{const c=document.querySelector('feiniu-music-card'),box=c.shadowRoot.querySelector('#lyric-lines'),row=box.children[8];return Math.abs(row.getBoundingClientRect().top+row.clientHeight/2-box.getBoundingClientRect().top-box.clientHeight/2)<2;});
  assert.equal(await page.evaluate(()=>calls.length),centreOnlyBefore,'Clicking lyric text centres it without seeking or resuming');
  assert(await first.locator('.lyric-row').nth(8).evaluate(e=>e.classList.contains('selected')));
  await first.locator('.lyric-row p').nth(9).press('Enter');
  assert.equal(await page.evaluate(()=>calls.length),centreOnlyBefore,'Keyboard lyric selection is also visual only');
  // Seek from a paused track, using adjusted time, then resume the same item.
  const seek=first.locator('.lyric-seek').nth(8);
  await seek.focus();await seek.press('Enter');
  assert.deepEqual(await page.evaluate(()=>calls.slice(-2).map(c=>[c.service,c.data])),[
    ['media_seek',{entity_id:'media_player.feiniu_a',seek_position:31.5}],['media_play',{entity_id:'media_player.feiniu_a'}],
  ]);
  // A refused seek cannot cause an unexpected resume.
  await page.evaluate(()=>{window.lyricOriginalService=hass.callService;hass.callService=async(d,s,data)=>{calls.push({domain:d,service:s,data});throw new Error('synthetic seek rejection');};});
  const failedBefore=await page.evaluate(()=>calls.length);
  await seek.focus();await seek.press('Enter');
  assert.equal(await page.evaluate(()=>calls.length),failedBefore+1);
  assert.equal(await page.evaluate(()=>calls.at(-1).service),'media_seek');
  await page.evaluate(()=>{hass.callService=lyricOriginalService;});
  // A song/output change while seeking must never resume another song/output.
  await page.evaluate(()=>{hass.callService=async(d,s,data)=>{calls.push({domain:d,service:s,data});if(s==='media_seek')return new Promise(resolve=>window.lyricSeekRelease=resolve);};});
  await seek.focus();await seek.press('Enter');
  await page.waitForFunction(()=>!!window.lyricSeekRelease);
  const staleBefore=await page.evaluate(()=>calls.length);
  await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.playback_round++;c.hass=hass;window.lyricSeekRelease();hass.callService=lyricOriginalService;});
  await page.waitForFunction(()=>!document.querySelector('feiniu-music-card')._lyricSeeking);
  assert.equal(await page.evaluate(()=>calls.length),staleBefore);
  await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.supported_features&=~2;c.hass=hass;});
  assert(await first.locator('.lyric-seek').first().isDisabled(),'No seek affordance when the output cannot seek');
  for(const width of [1280,390]){
    await page.setViewportSize({width,height:960});
    await first.evaluate(c=>{c._clearLyricInteraction();c.shadowRoot.activeElement?.blur();});
    await first.locator('.now-art').hover();
    assert(await first.locator('.lyric-seek').evaluateAll(buttons=>buttons.every(b=>getComputedStyle(b).opacity==='0')),'Disabled seek buttons stay hidden in both landscape and portrait');
  }
  // Plain lyrics have no timing controls; pending manual-follow work is cleared on detach.
  await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');c._lyrics=[];c._lyricText=Array.from({length:47},(_,i)=>`An untimed verse ${i+1}`).join('\n');c._renderContent();});
  assert.equal(await first.locator('#lyric-tools').isVisible(),false);
  assert.equal(await first.locator('.lyric-seek').count(),0);
  for(const width of [1280,390]){
    await page.setViewportSize({width,height:960});
    assert.equal(await first.locator('.plain-lyrics p').first().evaluate(e=>getComputedStyle(e).fontSize),width===1280?'28px':'19px');
    await first.locator('#lyric-lines').hover();await page.mouse.wheel(0,250);
    await page.waitForFunction(()=>document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-lines').scrollTop>100);
    await first.screenshot({path:`artifacts/card-preview/player-plain-${width}.png`});
  }
  await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity]=window.lyricTestState;c.hass=hass;c._lyrics=window.lyricTestLines;c._renderContent();c._animate();});
  // Content fades/slides, but HA's grid and the artwork's dimensions never interpolate.
  const transitionCommands=await page.evaluate(()=>calls.length);
  for(const tab of ['browse','lyrics']){
    const samples=await first.evaluate(async(c,tab)=>{
      const done=c._showTab(tab),result=[];
      for(let n=0;n<32;n++){
        await new Promise(requestAnimationFrame);const shell=c.shadowRoot.querySelector('.shell'),b=shell.getBoundingClientRect(),info=c.shadowRoot.querySelector('.now-info'),s=getComputedStyle(shell),v=getComputedStyle(info);
        result.push({tab:c._tab,shell:[b.x,b.y,b.width,b.height],layout:[s.gridTemplateColumns,s.gridTemplateRows,s.padding,info.offsetWidth,info.offsetHeight],opacity:Number(v.opacity),shift:new DOMMatrix(v.transform).m42});
      }
      await done;return {result,transition:getComputedStyle(c.shadowRoot.querySelector('.shell')).transitionProperty,animations:c._viewAnimations.length};
    },tab);
    assert.equal(samples.transition,'none');
    assert.equal(samples.animations,0,'Completed animation handles are released');
    assert(samples.result.some(s=>s.opacity>0&&s.opacity<1),`${tab}: a visible transition actually runs`);
    assert(samples.result.some(s=>s.shift>1&&s.shift<=24),`${tab}: content moves without scaling`);
    for(const phase of ['browse','lyrics']){
      const frames=samples.result.filter(s=>s.tab===phase);
      for(const frame of frames)assert.deepEqual(frame.layout,frames[0].layout,`${tab}: stable grid and text/artwork dimensions`);
    }
    for(const frame of samples.result)assert.deepEqual(frame.shell,samples.result[0].shell,'The card itself never moves/resizes');
  }
  await first.evaluate(async c=>{await c._showTab('browse');const opening=c._showTab('lyrics');await new Promise(r=>setTimeout(r,60));await c._showTab('browse');await opening;});
  assert.equal(await first.evaluate(c=>c._tab),'browse','Closing during entry finishes in the requested view');
  assert.equal(await first.evaluate(c=>c._viewAnimations.length),0);
  await first.evaluate(async c=>{await c._showTab('lyrics');await Promise.all([c._showTab('browse'),c._showTab('lyrics')]);});
  assert.equal(await first.evaluate(c=>c._tab),'lyrics','Rapid reverse navigation cannot let a stale close hide the player');
  assert.equal(await first.locator('.now-info').evaluate(e=>getComputedStyle(e).opacity),'1');
  assert.equal(await page.evaluate(()=>calls.length),transitionCommands,'Page animations send no playback commands');
  await page.emulateMedia({reducedMotion:'reduce'});
  await first.evaluate(async c=>{c._followLyrics();await c._showTab('browse');await c._showTab('lyrics');});
  assert.equal(await first.locator('.shell').evaluate(e=>getComputedStyle(e).transitionDuration),'0s');
  assert.equal(await first.evaluate(c=>c._viewAnimations.length),0,'Reduced motion skips the page animation');
  await page.emulateMedia({reducedMotion:'no-preference'});
  for(const width of [390,1280]){
    await page.setViewportSize({width,height:960});
    await first.evaluate(c=>{c._lyrics=Array.from({length:35},(_,i)=>({time_ms:i*4000,text:`A familiar song · ${i+1}`}));c._renderContent();c._animate();});
    await page.waitForFunction(()=>{const box=document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-lines'),r=box.getBoundingClientRect(),p=box.parentElement.getBoundingClientRect();return Math.abs(r.height-p.height)<1&&Math.abs(r.y-p.y)<1;});
    const line=first.locator('.lyric-row').nth(8);await line.scrollIntoViewIfNeeded();await line.hover();
    assert(await line.locator('.lyric-seek').evaluate(e=>{const b=e.getBoundingClientRect(),p=e.previousElementSibling.getBoundingClientRect();return b.x>=p.right&&b.right<=innerWidth;}),'Time button sits to the right without overlapping the lyric');
    if(width===390){
      assert(await line.locator('p').evaluate(p=>{const b=p.getBoundingClientRect(),box=p.closest('#lyric-lines').getBoundingClientRect();return Math.abs(b.x+b.width/2-box.x-box.width/2)<1;}),'Portrait lyric text centres on the whole panel, independent of its time button');
      assert(await first.evaluate(c=>{const q=s=>c.shadowRoot.querySelector(s),cover=q('.now-art').getBoundingClientRect(),title=q('#title'),meta=q('.now-meta'),r=title.getBoundingClientRect();return getComputedStyle(title).textAlign==='center'&&getComputedStyle(meta).justifyContent==='center'&&Math.abs(r.x+r.width/2-cover.x-cover.width/2)<1&&parseFloat(getComputedStyle(meta).fontSize)<parseFloat(getComputedStyle(title).fontSize);}), 'Portrait title/subtitle share the cover centre and retain a clear type hierarchy');
    }
    await line.locator('p').click();
    await page.waitForFunction(()=>{const c=document.querySelector('feiniu-music-card'),box=c.shadowRoot.querySelector('#lyric-lines'),row=box.children[8];return Math.abs(row.getBoundingClientRect().top+row.clientHeight/2-box.getBoundingClientRect().top-box.clientHeight/2)<2;});
    const depth=await first.evaluate(c=>{const b=c.shadowRoot.querySelector('#lyric-lines'),rect=b.getBoundingClientRect();return [...b.children].map(row=>({y:row.getBoundingClientRect().top+row.clientHeight/2-rect.top,blur:parseFloat(row.style.getPropertyValue('--lyric-blur'))})).filter(row=>row.y>=0&&row.y<=rect.height).sort((a,z)=>a.y-z.y);});
    assert(depth.some(d=>d.blur>1)&&depth.some(d=>d.blur===0),'Lyrics progressively blur toward the visible edges');
    const edgeIndex=await first.evaluate(c=>{const b=c.shadowRoot.querySelector('#lyric-lines'),rect=b.getBoundingClientRect();return [...b.children].findIndex(row=>{const r=row.getBoundingClientRect();return r.top>rect.top+12&&r.bottom<rect.bottom&&parseFloat(row.style.getPropertyValue('--lyric-blur'))>1;});});
    assert(edgeIndex>=0);
    const edge=first.locator('.lyric-row').nth(edgeIndex);await edge.hover();
    await page.waitForFunction(index=>{const p=document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-lines').children[index].querySelector('p'),s=getComputedStyle(p);return s.filter==='blur(0px)'&&s.opacity==='1';},edgeIndex);
    await line.hover();
    await page.screenshot({path:`artifacts/card-preview/lyric-controls-${width}.png`,fullPage:true});
  }
  await first.evaluate(c=>{c._lyrics=[];c._lyricText='';c._lyricResultKey='';c._lyricStatus='noLyrics';c._renderContent();});
  assert(await first.locator('#lyric-lines').evaluate(e=>getComputedStyle(e).paddingTop==='0px'&&e.scrollHeight<=e.clientHeight+1),'Missing lyrics do not inherit timed-line scroll padding or overflow');
  await first.evaluate(c=>{c._holdLyrics();c.remove();document.querySelector('.grid').prepend(c);});
  assert.equal(await first.evaluate(c=>c._lyricFollowTimer),0,'Detaching clears manual-follow timers');
  await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyrics.length>0);
  // A real touch context exercises hover:none, which desktop viewport resizing does not.
  const touchContext=await page.context().browser().newContext({viewport:{width:390,height:960},hasTouch:true,isMobile:true});
  try{
    const mobile=await touchContext.newPage();await mobile.goto(page.url());
    const card=mobile.locator('feiniu-music-card').first();await card.locator('.tile').first().waitFor();
    await mobile.evaluate(async()=>{document.querySelectorAll('feiniu-music-card')[1].remove();document.querySelector('.grid').style.display='block';const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].state='paused';c.hass=hass;await c._showTab('lyrics');});
    await mobile.waitForFunction(()=>document.querySelector('feiniu-music-card').shadowRoot.querySelectorAll('.lyric-row').length>0);
    assert(await card.locator('.lyric-seek').evaluateAll(buttons=>buttons.every(b=>getComputedStyle(b).opacity==='0')),'Touch: paused playback does not reveal every time button');
    assert.equal(await card.locator('#lyric-tools').evaluate(e=>getComputedStyle(e).opacity),'0');
    await card.locator('.lyric-row p').first().tap();
    assert.equal(await card.locator('.lyric-seek').evaluateAll(buttons=>buttons.filter(b=>Number(getComputedStyle(b).opacity)>0).length),1,'Touch: tapping lyric text reveals only the selected time button');
    await mobile.waitForFunction(()=>getComputedStyle(document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-tools')).opacity==='1');
    assert.equal(await mobile.evaluate(()=>calls.length),0,'Touch selection/offset reveal cannot control the audio');
    await mobile.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.supported_features&=~2;c.hass=hass;c._clearLyricInteraction();c.shadowRoot.activeElement?.blur();});
    await card.locator('.now-art').tap();
    assert(await card.locator('.lyric-seek').evaluateAll(buttons=>buttons.every(b=>getComputedStyle(b).opacity==='0')),'Touch: disabled time buttons are also hidden until their own line is selected');
  }finally{await touchContext.close();}
}
