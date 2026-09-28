import assert from 'node:assert/strict';

// Synthetic HA only: visual modes must never start or replace a real queue.
export async function checkCompactLyrics(sourcePage){
  const context=await sourcePage.context().browser().newContext(),page=await context.newPage(),errors=[];
  page.on('pageerror',err=>errors.push(err.message));page.setDefaultTimeout(5000);
  try{
    await page.setViewportSize({width:410,height:850});await page.goto(`${sourcePage.url()}?compact=1`);
    const first=page.locator('feiniu-music-card').first();
    await first.locator('#mini-open').waitFor();
    await page.evaluate(()=>{
      document.querySelectorAll('feiniu-music-card')[1].remove();document.querySelector('.grid').style.display='block';
      const text=['After the rain','Quiet room','A familiar song','Follows us home','Evening glow','Under the moon','We take our time','Let music stay','One more moment','Before dawn'];
      window.lyricFixture={text:text.join('\n'),synced_lines:text.map((text,i)=>({time_ms:i*4000,text}))};
      const state=hass.states['media_player.feiniu_a'];state.state='paused';state.attributes.media_position=13;
      const c=document.querySelector('feiniu-music-card');c.setConfig({entity:'media_player.feiniu_a',display_mode:'compact',compact_view:'auto',compact_background:'artwork'});c.hass=hass;
    });
    await first.locator('.lyric-row.current').waitFor();
    const height=(await first.boundingBox()).height;
    assert.equal(height,425,'Rich compact card has the requested total height');
    assert.equal(Math.round((await first.locator('.compact-heading').boundingBox()).height),32,'Header really shrinks by 14px instead of only changing text direction');
    assert.equal(Math.round((await first.locator('#compact-stage').boundingBox()).height),189,'Added height goes to lyrics');
    assert.equal(Math.round((await first.locator('#lyric-lines').boundingBox()).height),189,'Offset toolbar consumes no lyric height');
    assert(await first.evaluate(c=>c.getGridOptions().rows===8),'HA reserves enough grid space for the taller lyrics card');
    assert(await first.locator('.compact-labels').evaluate(e=>{const a=e.firstElementChild.getBoundingClientRect(),b=e.lastElementChild.getBoundingClientRect();return b.left>a.right&&Math.abs(a.bottom-b.bottom)<5;}),'Card and output names share one header line');
    assert.equal(await first.locator('.lyric-row.current p').textContent(),'Follows us home');
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/lyrics').length),1);
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type!=='feiniu_music/lyrics').length),0,'Inline lyrics do not browse the library or fetch queue pages');
    await page.mouse.move(0,0);
    assert.equal(await first.locator('.lyric-seek').evaluateAll(bs=>bs.filter(b=>Number(getComputedStyle(b).opacity)>0).length),0,'Pausing does not reveal every timestamp');
    assert.equal(await first.evaluate(c=>c._raf),0,'Paused cards do not keep an animation loop running');
    await page.waitForFunction(()=>{const c=document.querySelector('feiniu-music-card'),s=c.shadowRoot,img=s.querySelector('.compact-background img.visible');return img?.naturalWidth>0&&Number(getComputedStyle(img).opacity)>.71&&getComputedStyle(s.querySelector('.lyric-panel')).opacity==='1';});
    await first.screenshot({path:'artifacts/card-preview/compact-lyrics-dark.png'});
    for(const width of [320,420,700]){
      await page.setViewportSize({width,height:850});
      await page.waitForFunction(()=>{const r=document.querySelector('feiniu-music-card').shadowRoot,b=r.querySelector('#lyric-lines').getBoundingClientRect(),p=r.querySelector('.lyric-row.current p').getBoundingClientRect();return Math.abs(p.top+p.height/2-b.top-b.height/2)<1;});
      const visible=await first.locator('.lyric-row').evaluateAll(rows=>{const box=rows[0].parentElement.getBoundingClientRect();return rows.map(row=>{const r=row.querySelector('p').getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,fontSize:parseFloat(getComputedStyle(row.querySelector('p')).fontSize),gap:parseFloat(getComputedStyle(row).marginBottom),blur:parseFloat(row.style.getPropertyValue('--lyric-blur')),opacity:parseFloat(row.style.getPropertyValue('--lyric-opacity'))};}).filter(r=>r.top>=box.top&&r.bottom<=box.bottom);});
      assert.equal((await first.boundingBox()).height,425);
      assert.equal(visible.length,5,'Five complete short lines fit, not just five clipped line centres');
      assert(visible.every(r=>Math.abs(r.height-25.6)<.05&&r.fontSize===16&&r.gap===12&&r.opacity>=.46),'Five lines use the original 16px type, 25.6px line height and 12px spacing');
      assert(visible[0].blur>visible[1].blur&&visible[1].blur>visible[2].blur&&visible[2].blur===0&&visible[4].blur>visible[3].blur,'Blur increases gradually on both sides of the centre');
      await first.screenshot({path:`artifacts/card-preview/compact-five-lines-${width}.png`});
    }
    const edge=first.locator('.lyric-row').nth(1);
    await edge.hover();
    await page.waitForFunction(()=>{const p=document.querySelector('feiniu-music-card').shadowRoot.querySelectorAll('.lyric-row p')[1],s=getComputedStyle(p);return s.filter==='blur(0px)'&&s.opacity==='1';});
    await page.mouse.move(0,0);
    const oldBlur=await edge.evaluate(e=>parseFloat(e.style.getPropertyValue('--lyric-blur')));
    await first.locator('#lyric-lines').evaluate(e=>{e.scrollTop+=4;});
    await page.waitForFunction(old=>parseFloat(document.querySelector('feiniu-music-card').shadowRoot.querySelectorAll('.lyric-row')[1].style.getPropertyValue('--lyric-blur'))>old,oldBlur);
    const newBlur=await edge.evaluate(e=>parseFloat(e.style.getPropertyValue('--lyric-blur')));
    assert(newBlur-oldBlur<.2,'A small scroll updates blur smoothly instead of toggling a visibility threshold');
    await page.setViewportSize({width:410,height:850});
    await first.evaluate(c=>c._centreLyric(c._lastLine));
    assert.equal(await first.locator('.shell').evaluate(e=>getComputedStyle(e,'::after').backdropFilter),'blur(80px)');
    assert.equal(await first.locator('#compact-toggle,#compact-artwork').count(),0,'There is no duplicate cover or cover/lyrics switch');
    await first.evaluate(c=>{hass.states[c._config.entity].attributes.entity_picture='/cover.svg?i=3';c.hass=hass;});
    await page.waitForFunction(()=>{const imgs=[...document.querySelector('feiniu-music-card').shadowRoot.querySelectorAll('.compact-background img')];return imgs.some(i=>i.classList.contains('visible')&&i.getAttribute('src').endsWith('i=3')&&Number(getComputedStyle(i).opacity)>.71)&&imgs.every(i=>i.classList.contains('visible')||getComputedStyle(i).opacity==='0');});
    assert.equal((await first.boundingBox()).height,height,'Cover color changes cannot reflow the card');
    const stableArt=await first.evaluate(c=>{const images=[...c.shadowRoot.querySelectorAll('.compact-background img')],sources=images.map(i=>i.getAttribute('src'));c.hass=hass;return images.every((img,i)=>img===c.shadowRoot.querySelectorAll('.compact-background img')[i]&&img.getAttribute('src')===sources[i]);});
    assert(stableArt,'Progress updates reuse the same decorative images');
    await page.screenshot({path:'artifacts/card-preview/compact-lyrics-warm.png',fullPage:true});
    const before=await page.evaluate(()=>calls.length);
    await first.locator('.lyric-row.current p').click();
    assert.equal(await page.evaluate(()=>calls.length),before,'Selecting lyric text only centers it');
    assert.equal(await first.locator('.lyric-seek').evaluateAll(bs=>bs.filter(b=>Number(getComputedStyle(b).opacity)>0).length),1);
    await first.locator('.lyric-row.selected .lyric-seek').click();
    assert.deepEqual(await page.evaluate(()=>calls.slice(-2)),[
      {domain:'media_player',service:'media_seek',data:{entity_id:'media_player.feiniu_a',seek_position:12}},
      {domain:'media_player',service:'media_play',data:{entity_id:'media_player.feiniu_a'}},
    ]);
    const afterSeek=await page.evaluate(()=>calls.length);
    const node=await first.locator('.lyric-panel').elementHandle();
    await first.locator('#mini-open').click();await first.locator('#expanded-dialog[open]').waitFor();
    await first.locator('#expanded-close button').click();
    assert(await node.evaluate(e=>e.parentElement.id==='compact-stage'),'Expansion shares one lyric panel and returns it to the compact card');
    assert.equal((await first.boundingBox()).height,height);
    assert.equal(await first.locator('.lyric-row.current p').textContent(),'Follows us home');
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/lyrics').length),1,'View changes reuse the successful current-round response');
    assert.equal(await page.evaluate(()=>calls.length),afterSeek);

    // New rounds clear old lines immediately and reject a late previous response.
    await page.evaluate(()=>{linesDeferred=true;hass.states['media_player.feiniu_a'].attributes.playback_round++;document.querySelector('feiniu-music-card').hass=hass;});
    await page.waitForFunction(()=>!!window.releaseLyrics);
    assert.equal(await first.locator('.lyric-row').count(),0);
    assert((await first.boundingBox()).height<300,'Auto collapses to simple while the next lyric result is unknown');
    await page.evaluate(()=>{
      const old=releaseLyrics;linesDeferred=null;lyricFixture={text:'',synced_lines:[]};
      hass.states['media_player.feiniu_a'].attributes.playback_round++;document.querySelector('feiniu-music-card').hass=hass;
      old({text:'STALE COMPACT LYRICS',synced_lines:[]});
    });
    await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyricStatus==='noLyrics');
    assert.equal(await first.locator('#compact-stage').isVisible(),false,'Auto without lyrics is a simple card');
    assert(!(await first.locator('#lyric-lines').textContent()).includes('STALE'));
    const simpleHeight=(await first.boundingBox()).height;assert(simpleHeight<300);
    assert(await first.evaluate(c=>c.getGridOptions().rows===5&&c.getCardSize()===5));
    await page.screenshot({path:'artifacts/card-preview/compact-auto-no-lyrics.png',fullPage:true});
    await first.evaluate(c=>{c.setConfig({...c._config,compact_view:'lyrics'});c.hass=hass;});
    assert((await first.locator('#lyric-lines').textContent()).includes('暂无歌词'));
    assert.equal((await first.boundingBox()).height,height,'Explicit lyrics mode keeps the lyric region even without lyrics');
    // In lyrics mode a pending response must show loading, never a cover fallback.
    await page.evaluate(()=>{linesDeferred=true;hass.states['media_player.feiniu_a'].attributes.playback_round++;document.querySelector('feiniu-music-card').hass=hass;});
    await page.waitForFunction(()=>!!window.releaseLyrics&&document.querySelector('feiniu-music-card')._lyricStatus==='loading');
    assert(await first.locator('#lyric-lines').isVisible());assert((await first.locator('#lyric-lines').textContent()).includes('加载'));
    assert.equal((await first.boundingBox()).height,height);
    await page.screenshot({path:'artifacts/card-preview/compact-lyrics-loading.png',fullPage:true});
    await page.evaluate(()=>{linesDeferred=null;releaseLyrics({text:'',synced_lines:[]});});
    await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyricStatus==='noLyrics');
    await first.evaluate(c=>{c.setConfig({...c._config,compact_view:'auto'});c.hass=hass;});

    await page.evaluate(()=>{lyricFixture={text:'Plain words\nWithout timestamps',synced_lines:[]};hass.states['media_player.feiniu_a'].attributes.playback_round++;document.querySelector('feiniu-music-card').hass=hass;});
    await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyricText.startsWith('Plain'));
    assert(await first.locator('#compact-stage').isVisible(),'Auto displays available untimed lyrics without inventing synchronization');
    assert(await first.locator('#lyric-lines pre').isVisible());assert.equal(await first.locator('.lyric-seek').count(),0);
    assert.equal((await first.boundingBox()).height,height);

    for(const phase of ['loading','detached','failed']){
      await first.evaluate((c,phase)=>{hass.states[c._config.entity].attributes.session_phase=phase;c.hass=hass;},phase);
      assert(await first.locator('#lyric-lines pre').isVisible());
      assert(await first.locator('#compact-status').isVisible());
      assert.equal(await first.locator('#compact-caption').count(),0,'No status strip overlays the lyrics');
      assert(await first.locator('#compact-status').evaluate(e=>{const r=e.getBoundingClientRect(),s=e.parentElement.querySelector('input').getBoundingClientRect(),a=e.parentElement.querySelector('#elapsed').getBoundingClientRect(),b=e.parentElement.querySelector('#duration').getBoundingClientRect();return r.top>s.bottom&&r.left>=a.left+30&&r.right<=b.right-30&&getComputedStyle(e).backgroundColor==='rgba(0, 0, 0, 0)';}));
      if(phase==='loading'){
        await first.locator('#button-play').focus();await page.keyboard.press('Tab');
        assert(await first.locator('#button-next').evaluate(e=>e.matches(':focus-visible')&&getComputedStyle(e).outlineStyle==='solid'),'Keyboard focus remains visibly marked');
        await page.screenshot({path:'artifacts/card-preview/compact-playback-loading.png',fullPage:true});
      }else{
        assert(await first.locator('#compact-status').textContent());
        await page.screenshot({path:`artifacts/card-preview/compact-status-${phase}.png`,fullPage:true});
      }
      assert.equal((await first.boundingBox()).height,height);
    }
    await first.evaluate(c=>{hass.states[c._config.entity].state='unavailable';c.hass=hass;});
    assert(await first.locator('#button-play').isDisabled());assert.equal((await first.boundingBox()).height,height);
    assert.equal(await first.locator('#compact-status').textContent(),'设备离线');

    // Restore synchronized lyrics and inspect narrow/light/reconfigured cards.
    await page.evaluate(()=>{
      lyricFixture={text:'Back home\nThe music stays with us through another quiet evening\nAnother quiet day',synced_lines:[{time_ms:0,text:'Back home'},{time_ms:4000,text:'The music stays with us through another quiet evening'},{time_ms:8000,text:'Another quiet day'}]};
      const a=hass.states['media_player.feiniu_a'];a.state='paused';Object.assign(a.attributes,{session_phase:'playing',media_position:5,playback_round:20});
      document.querySelector('feiniu-music-card').hass=hass;
    });
    await first.locator('.lyric-row.current').waitFor();
    await first.evaluate(c=>{hass.states[c._config.entity].attributes.supported_features&=~2;c.hass=hass;c._clearLyricInteraction();c.shadowRoot.activeElement?.blur();});
    await page.mouse.move(0,0);
    assert(await first.locator('.lyric-seek').evaluateAll(bs=>bs.every(b=>b.disabled&&getComputedStyle(b).opacity==='0')),'Missing seek support never exposes a row of disabled timestamp buttons');
    await first.evaluate(c=>{hass.states[c._config.entity].attributes.supported_features|=2;c.hass=hass;});
    for(const width of [320,390,700]){
      await page.setViewportSize({width,height:850});
      await page.mouse.move(0,0);
      assert.equal((await first.boundingBox()).height,height,'Width changes preserve the rich card height');
      assert(await first.evaluate(c=>{const r=c.shadowRoot,h=r.querySelector('.compact-heading').getBoundingClientRect(),b=r.querySelector('#compact-open button').getBoundingClientRect(),l=r.querySelector('.compact-labels').getBoundingClientRect(),i=r.querySelector('.mini-info').getBoundingClientRect();return h.height===32&&b.width===34&&b.height===34&&l.right+8<=b.left&&b.bottom<i.top;}),'Shorter header keeps the full expand target clear of labels and artwork');
      assert(await first.evaluate(c=>c.shadowRoot.querySelector('.shell').scrollWidth<=c.clientWidth+1));
      assert(await first.locator('#controls button:not([hidden]),#dock-tools>button.queue-toggle,#volume-toggle').evaluateAll(bs=>bs.filter(b=>b.getBoundingClientRect().width).every(b=>{const r=b.getBoundingClientRect();return Math.abs(r.width-r.height)<.5&&getComputedStyle(b).borderRadius==='50%';})),'Transport hit areas and focus outlines stay circular at every compact width');
      await first.locator('#volume-toggle').click();
      const pop=await first.locator('#volume-pop').boundingBox(),card=await first.boundingBox();
      assert(pop.x>=card.x&&pop.x+pop.width<=card.x+card.width+1&&pop.y>=card.y,'Volume stays inside the small card');
      await first.locator('#volume-close button').click();
      await first.locator('.lyric-row.current p').click();
      const area=await first.locator('#lyric-lines').boundingBox();
      await page.mouse.move(area.x+area.width/2,area.y+area.height/2);await page.mouse.wheel(0,18);
      await page.waitForFunction(()=>Number(getComputedStyle(document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-tools')).opacity)===1);
      assert(await first.evaluate(c=>{const r=c.shadowRoot,t=r.querySelector('#lyric-tools').getBoundingClientRect(),v=r.querySelector('#lyric-lines').getBoundingClientRect(),p=r.querySelector('.lyric-row.current p').getBoundingClientRect();return Math.abs(v.height-r.querySelector('.lyric-panel').clientHeight)<1&&t.left>=v.left&&t.right+8<=p.left&&t.top>=v.top&&t.bottom<=v.bottom;}),'Offset toolbar uses the left gutter without covering words or taking a separate row');
      await first.locator('.lyric-row.current p').click();
      const seek=first.locator('.lyric-row.selected .lyric-seek');await seek.hover();
      assert(await seek.evaluate(b=>{const r=b.getBoundingClientRect();return b.contains(b.getRootNode().elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),'Timestamp remains the clickable target while offset buttons are visible');
      await first.screenshot({path:`artifacts/card-preview/compact-lyrics-${width}.png`});
    }
    await page.setViewportSize({width:410,height:850});
    await first.evaluate(c=>{c.setConfig({...c._config,theme:'light',compact_view:'lyrics'});c.hass=hass;});
    await first.locator('.lyric-row.current').waitFor();
    await page.screenshot({path:'artifacts/card-preview/compact-lyrics-light.png',fullPage:true});
    assert.equal((await first.boundingBox()).height,height);
    const cached=await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/lyrics').length);
    await first.evaluate(c=>{c.remove();document.querySelector('.grid').append(c);});
    await first.locator('.lyric-row.current').waitFor();
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/lyrics').length),cached,'Masonry reconnect reuses only the matching current-round result');
    const options=await page.evaluate(()=>{
      const e=customElements.get('feiniu-music-card').getConfigElement();e.setConfig({entity:'media_player.feiniu_a',display_mode:'compact',compact_background:'artwork'});e.hass=hass;
      const schema=e.shadowRoot.querySelector('ha-form').schema;return ['compact_view','compact_background','compact_mask'].map(name=>schema.find(s=>s.name===name).selector.select.options.map(o=>o.value));
    });
    assert.deepEqual(options,[['simple','lyrics','auto'],['default','artwork'],['soft','glass']]);
    for(const theme of ['dark','light'])for(const compact_mask of ['soft','glass']){
      await first.evaluate((c,config)=>{c.setConfig({...c._config,...config});c.hass=hass;},{theme,compact_mask});
      await first.locator('.lyric-row.current').waitFor();
      assert.equal(await first.locator('.shell').evaluate(e=>getComputedStyle(e,'::after').backdropFilter),compact_mask==='soft'?'blur(80px)':'blur(12px)');
      assert.equal((await first.boundingBox()).height,height,'Overlay choice does not change player layout');
      await page.mouse.move(0,0);
      await page.waitForFunction(theme=>{const r=document.querySelector('feiniu-music-card').shadowRoot;return getComputedStyle(r.querySelector('.lyric-panel')).opacity==='1'&&Number(getComputedStyle(r.querySelector('.compact-background img.visible')).opacity)>(theme==='light'?.23:.71);},theme);
      await page.screenshot({path:`artifacts/card-preview/compact-${compact_mask}-${theme}.png`,fullPage:true});
    }
    const preserved=await page.evaluate(()=>{
      const e=customElements.get('feiniu-music-card').getConfigElement();e.setConfig({entity:'media_player.feiniu_a',display_mode:'compact',compact_background:'artwork',compact_mask:'glass'});e.hass=hass;
      const f=e.shadowRoot.querySelector('ha-form');f.dispatchEvent(new CustomEvent('value-changed',{detail:{value:{...f.data,compact_background:'default'}}}));
      const hidden=!f.schema.some(s=>s.name==='compact_mask');f.dispatchEvent(new CustomEvent('value-changed',{detail:{value:{...f.data,compact_background:'artwork'}}}));
      return hidden&&f.data.compact_mask==='glass'&&f.schema.some(s=>s.name==='compact_mask');
    });assert(preserved,'Background switching retains the selected mask');
    await first.evaluate(c=>{c.setConfig({...c._config,theme:'dark',compact_background:'default'});c.hass=hass;});
    await first.locator('.lyric-row.current').waitFor();
    assert.equal((await first.boundingBox()).height,height,'Background choice is independent of content size');
    assert.equal(await first.locator('.shell').evaluate(e=>getComputedStyle(e).backdropFilter),'none');
    assert.equal(await first.locator('#compact-background').isVisible(),false);
    await page.screenshot({path:'artifacts/card-preview/compact-lyrics-original-background.png',fullPage:true});
    assert.equal(await page.evaluate(()=>calls.length),afterSeek,'Visual state changes never send additional playback commands');
    assert.deepEqual(errors,[]);
  }finally{await context.close();}
  const touch=await sourcePage.context().browser().newContext({viewport:{width:390,height:850},hasTouch:true,isMobile:true});
  try{
    const mobile=await touch.newPage();await mobile.goto(`${sourcePage.url()}?compact=1`);
    const card=mobile.locator('feiniu-music-card').first();await card.locator('#mini-open').waitFor();
    await mobile.evaluate(()=>{document.querySelectorAll('feiniu-music-card')[1].remove();document.querySelector('.grid').style.display='block';const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].state='paused';c.setConfig({...c._config,compact_view:'lyrics'});c.hass=hass;});
    await card.locator('.lyric-row.current').waitFor();
    assert.equal(await card.locator('.lyric-seek').evaluateAll(bs=>bs.filter(b=>Number(getComputedStyle(b).opacity)>0).length),0);
    await card.locator('.lyric-row.current p').tap();
    await mobile.waitForFunction(()=>getComputedStyle(document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-tools')).opacity==='1');
    assert.equal(await card.locator('.lyric-seek').evaluateAll(bs=>bs.filter(b=>Number(getComputedStyle(b).opacity)>0).length),1,'Compact touch only reveals the selected timestamp');
    assert(await card.evaluate(c=>{const r=c.shadowRoot,t=r.querySelector('#lyric-tools').getBoundingClientRect(),p=r.querySelector('.lyric-row.current p').getBoundingClientRect();return t.right+8<=p.left;}),'Compact touch offset controls stay in their left gutter');
    assert.equal(await mobile.evaluate(()=>calls.length),0);
    await card.locator('.lyric-row.selected .lyric-seek').tap();
    assert.deepEqual(await mobile.evaluate(()=>calls.map(c=>c.service)),['media_seek','media_play'],'Touch timestamp hits seek, never an overlapping offset button');
    assert.equal(await mobile.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').length),0);
    const services=await mobile.evaluate(()=>calls.length);
    await card.locator('#lyricEarlier').tap();
    assert.deepEqual(await mobile.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').map(m=>m.lyric_offset)),[.5],'Left offset control sends only the display offset');
    assert.equal(await mobile.evaluate(()=>calls.length),services,'Adjusting the offset does not seek or change playback');
  }finally{await touch.close();}
}
