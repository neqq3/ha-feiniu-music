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
      const text=['After the rain','The room grows quiet','A familiar song','Follows us home','Through the evening','Under the moon','We take our time','Let the music stay','One more moment','Before the morning'];
      window.lyricFixture={text:text.join('\n'),synced_lines:text.map((text,i)=>({time_ms:i*4000,text}))};
      const state=hass.states['media_player.feiniu_a'];state.state='paused';state.attributes.media_position=13;
      const c=document.querySelector('feiniu-music-card');c.setConfig({entity:'media_player.feiniu_a',display_mode:'compact',compact_view:'auto',compact_background:'artwork'});c.hass=hass;
    });
    await first.locator('.lyric-row.current').waitFor();
    const height=(await first.boundingBox()).height;
    assert(height>=350&&height<410,'Rich compact card stays within a dashboard-sized footprint');
    assert.equal(await first.locator('.lyric-row.current p').textContent(),'Follows us home');
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/lyrics').length),1);
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type!=='feiniu_music/lyrics').length),0,'Inline lyrics do not browse the library or fetch queue pages');
    await page.mouse.move(0,0);
    assert.equal(await first.locator('.lyric-seek').evaluateAll(bs=>bs.filter(b=>Number(getComputedStyle(b).opacity)>0).length),0,'Pausing does not reveal every timestamp');
    assert.equal(await first.evaluate(c=>c._raf),0,'Paused cards do not keep an animation loop running');
    await page.waitForFunction(()=>{const c=document.querySelector('feiniu-music-card'),s=c.shadowRoot,img=s.querySelector('.compact-background img.visible');return img?.naturalWidth>0&&Number(getComputedStyle(img).opacity)>.71&&getComputedStyle(s.querySelector('.lyric-panel')).opacity==='1';});
    await page.screenshot({path:'artifacts/card-preview/compact-lyrics-dark.png',fullPage:true});
    assert((await first.locator('.shell').evaluate(e=>getComputedStyle(e).backdropFilter)).includes('blur'),'The card has an actual frosted backdrop');
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
    await first.locator('#compact-toggle button').click();
    assert(await first.locator('#compact-artwork').isVisible());
    assert.equal((await first.boundingBox()).height,height);
    await first.locator('#compact-toggle button').click();
    await first.locator('.lyric-row.current').waitFor();
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
    assert.equal((await first.boundingBox()).height,height);
    await page.evaluate(()=>{
      const old=releaseLyrics;linesDeferred=null;lyricFixture={text:'',synced_lines:[]};
      hass.states['media_player.feiniu_a'].attributes.playback_round++;document.querySelector('feiniu-music-card').hass=hass;
      old({text:'STALE COMPACT LYRICS',synced_lines:[]});
    });
    await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyricStatus==='noLyrics');
    assert(await first.locator('#compact-artwork').isVisible(),'Auto mode uses artwork for a song without lyrics');
    assert(!(await first.locator('#lyric-lines').textContent()).includes('STALE'));
    assert.equal((await first.boundingBox()).height,height);
    await first.locator('#compact-toggle button').click();
    assert((await first.locator('#lyric-lines').textContent()).includes('暂无歌词'));

    await page.evaluate(()=>{lyricFixture={text:'Plain words\nWithout timestamps',synced_lines:[]};hass.states['media_player.feiniu_a'].attributes.playback_round++;document.querySelector('feiniu-music-card').hass=hass;});
    await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyricText.startsWith('Plain'));
    assert(await first.locator('#compact-artwork').isVisible(),'Auto does not invent synchronization for plain text');
    await first.locator('#compact-toggle button').click();
    assert(await first.locator('#lyric-lines pre').isVisible());assert.equal(await first.locator('.lyric-seek').count(),0);
    assert.equal((await first.boundingBox()).height,height);

    for(const phase of ['loading','detached','failed']){
      await first.evaluate((c,phase)=>{hass.states[c._config.entity].attributes.session_phase=phase;c.hass=hass;},phase);
      assert(await first.locator('#compact-artwork').isVisible());assert(await first.locator('#compact-toggle button').isDisabled());
      assert(await first.locator('#compact-caption').textContent());assert.equal((await first.boundingBox()).height,height);
    }
    await first.evaluate(c=>{hass.states[c._config.entity].state='unavailable';c.hass=hass;});
    assert(await first.locator('#button-play').isDisabled());assert.equal((await first.boundingBox()).height,height);

    // Restore synchronized lyrics and inspect narrow/light/reconfigured cards.
    await page.evaluate(()=>{
      lyricFixture={text:'Back home\nThe music stays\nAnother quiet day',synced_lines:[{time_ms:0,text:'Back home'},{time_ms:4000,text:'The music stays'},{time_ms:8000,text:'Another quiet day'}]};
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
      assert(await first.evaluate(c=>c.shadowRoot.querySelector('.shell').scrollWidth<=c.clientWidth+1));
      await first.locator('#volume-toggle').click();
      const pop=await first.locator('#volume-pop').boundingBox(),card=await first.boundingBox();
      assert(pop.x>=card.x&&pop.x+pop.width<=card.x+card.width+1&&pop.y>=card.y,'Volume stays inside the small card');
      await first.locator('#volume-close button').click();
      await page.screenshot({path:`artifacts/card-preview/compact-lyrics-${width}.png`,fullPage:true});
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
      const e=customElements.get('feiniu-music-card').getConfigElement();e.setConfig({entity:'media_player.feiniu_a',display_mode:'compact'});e.hass=hass;
      const schema=e.shadowRoot.querySelector('ha-form').schema;return ['compact_view','compact_background'].map(name=>schema.find(s=>s.name===name).selector.select.options.map(o=>o.value));
    });
    assert.deepEqual(options,[['simple','lyrics','auto'],['default','artwork']]);
    await first.evaluate(c=>{c.setConfig({...c._config,theme:'dark',compact_background:'default'});c.hass=hass;});
    await first.locator('.lyric-row.current').waitFor();
    assert.equal((await first.boundingBox()).height,height,'Background choice is independent of content size');
    assert.equal(await first.locator('.shell').evaluate(e=>getComputedStyle(e).backdropFilter),'none');
    assert.equal(await first.locator('#compact-background').isVisible(),false);
    await page.screenshot({path:'artifacts/card-preview/compact-lyrics-original-background.png',fullPage:true});
    assert.equal(await page.evaluate(()=>calls.length),afterSeek,'Visual state changes never send additional playback commands');
    assert.deepEqual(errors,[]);
  }finally{await context.close();}
}
