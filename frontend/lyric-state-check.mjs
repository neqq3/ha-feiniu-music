import assert from 'node:assert/strict';

// A restored queue retains its current occurrence but has no resolved media
// metadata yet. Exercise that real HA state separately from normal playback.
export async function checkLyricState(browser, baseURL) {
  const page=await browser.newPage({viewport:{width:520,height:1100}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));page.setDefaultTimeout(5000);
  try {
    await page.goto(`${baseURL}?compact=1`);
    const first=page.locator('feiniu-music-card').first(),second=page.locator('feiniu-music-card').nth(1);
    await first.locator('#mini-open').waitFor();
    await page.evaluate(async()=>{
      const a=hass.states['media_player.feiniu_a'];a.state='idle';
      Object.assign(a.attributes,{session_phase:'restored',queue_active:false,playback_round:0});
      for(const key of ['media_title','media_artist','media_album_name','entity_picture','media_duration','media_position'])delete a.attributes[key];
      document.querySelectorAll('feiniu-music-card').forEach(c=>{
        c.setConfig({...c._config,compact_view:'auto'});c.hass=hass;
      });
      await Promise.resolve();
    });
    const requests=()=>page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/lyrics'&&m.entity_id==='media_player.feiniu_a').length);
    assert.equal(await first.locator('#mini-title').textContent(),'尚未选择歌曲');
    assert.equal(await requests(),0,'A restored occurrence without current metadata must not fetch lyrics');
    assert.equal(await first.locator('.lyric-row,.plain-lyrics').count(),0);
    assert.equal(await first.locator('#compact-stage').isVisible(),false,'Auto stays simple until a current song is available');
    await second.locator('.lyric-row').first().waitFor();
    const assertEmpty=async()=>{
      assert.equal(await first.locator('.lyric-row,.plain-lyrics').count(),0);
      assert.equal(await first.locator('#lyric-tools').isVisible(),false);
      assert.equal(await first.locator('#compact-stage').isVisible(),false);
      assert.equal(await second.locator('.lyric-row').count(),2,'The other output retains its lyrics');
    };
    // Explicit lyric view and the expanded player show an empty-state message.
    await first.evaluate(c=>{c.setConfig({...c._config,compact_view:'lyrics'});c.hass=hass;});
    assert.match(await first.locator('#lyric-lines').textContent(),/暂无歌词/);
    assert.equal(await first.locator('.lyric-row').count(),0);
    await first.locator('#mini-open').click();
    await first.locator('#expanded-dialog[open]').waitFor();
    assert.match(await first.locator('#lyric-lines').textContent(),/暂无歌词/);
    assert.equal(await requests(),0);
    await first.locator('#expanded-close button').click();
    await first.evaluate(c=>{c.setConfig({...c._config,compact_view:'auto'});c.hass=hass;});

    // Metadata can arrive without changing either the occurrence or round.
    await first.evaluate(c=>{
      const a=hass.states[c._config.entity];a.state='buffering';
      Object.assign(a.attributes,{media_title:'Resolved song',media_artist:'Synthetic artist',media_duration:180,session_phase:'loading'});
      c.hass=hass;
    });
    await first.locator('.lyric-row').first().waitFor();
    assert.equal(await requests(),1,'Late metadata starts the first lyric read in the same round');
    assert.equal(await first.locator('#mini-title').textContent(),'Resolved song');
    assert(await first.locator('#compact-stage').isVisible());
    await first.evaluate(c=>{
      const s=hass.states[c._config.entity];s.state='paused';
      Object.assign(s.attributes,{session_phase:'paused',queue_active:true,media_position:1,media_position_updated_at:new Date().toISOString()});c.hass=hass;
    });
    assert.equal(await first.locator('.lyric-row').count(),2,'Pausing retains current lyrics');
    assert.equal(await requests(),1,'Pause does not refetch unchanged lyrics');
    await first.evaluate(c=>{
      const s=hass.states[c._config.entity];s.state='idle';
      delete s.attributes.media_title;Object.assign(s.attributes,{session_phase:'restored',queue_active:false});c.hass=hass;
    });
    await assertEmpty();
    assert.equal(await requests(),1,'Metadata loss clears lyrics without a new request');

    // Late in-flight lyrics cannot resurrect a song whose metadata was cleared.
    await first.evaluate(c=>{linesDeferred=true;hass.states[c._config.entity].attributes.media_title='Pending song';c.hass=hass;});
    await page.waitForFunction(()=>!!window.releaseLyrics);
    await first.evaluate(c=>{delete hass.states[c._config.entity].attributes.media_title;c.hass=hass;});
    await page.evaluate(async()=>{linesDeferred=null;releaseLyrics({text:'STALE LYRICS',synced_lines:[{time_ms:0,text:'STALE LYRICS'}]});await Promise.resolve();});
    await assertEmpty();
    await first.evaluate(c=>{hass.states[c._config.entity].attributes.media_title='Returned song';c.hass=hass;});
    await first.locator('.lyric-row').first().waitFor();
    assert.equal(await requests(),3,'Returning metadata can retry, even for the same occurrence and round');
    assert(!(await first.locator('#lyric-lines').textContent()).includes('STALE'));

    // Untimed lyrics follow the same lifecycle, including a cleared queue.
    await first.evaluate(c=>{
      lyricFixture={text:'Untimed verse\nAnother verse',synced_lines:[]};
      hass.states[c._config.entity].attributes.playback_round++;c.hass=hass;
    });
    await first.locator('.plain-lyrics').waitFor();
    await first.evaluate(c=>{hass.states[c._config.entity].attributes.media_title=null;c.hass=hass;});
    await assertEmpty();
    await first.evaluate(c=>{hass.states[c._config.entity].attributes.media_title='Untimed song';c.hass=hass;});
    await first.locator('.plain-lyrics').waitFor();
    await first.evaluate(c=>{hass.states[c._config.entity].attributes.queue_item_id=null;c.hass=hass;});
    await assertEmpty();
    assert.equal(await page.evaluate(()=>calls.length),0,'Empty-state rendering never controls playback or the queue');
    assert.deepEqual(errors,[]);
    console.log('Lyric state passed: restored queue, explicit/auto/modal views, late metadata, pause, metadata loss, stale response, plain lyrics, independent outputs.');
  } finally {await page.close();}
}
