import assert from 'node:assert/strict';

// Exercise the real card in the Sections sizing contract: 56px cells, 8px gaps.
// HA queries getGridOptions when constructing the wrapper, before async lyrics
// arrive; changing the return value later does not resize that existing slot.
export async function checkCompactLayout(browser, baseURL) {
  const context=await browser.newContext(),page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));page.setDefaultTimeout(5000);
  try {
    await page.setViewportSize({width:520,height:1200});
    await page.goto(`${baseURL}?compact=1`);
    await page.locator('feiniu-music-card').first().locator('#mini-open').waitFor();
    await page.evaluate(()=>{
      const grid=document.querySelector('.grid');grid.replaceChildren();
      grid.style.cssText='display:grid;grid-template-columns:repeat(12,minmax(0,1fr));grid-auto-rows:minmax(56px,auto);gap:8px';
      window.layoutPending=[];const original=hass.callWS;
      hass.callWS=message=>message.type==='feiniu_music/lyrics'
        ?new Promise(resolve=>layoutPending.push({entity:message.entity_id,resolve}))
        :original(message);
      for(const key of ['a','b']){
        const c=document.createElement('feiniu-music-card');
        c.setConfig({entity:`media_player.feiniu_${key}`,display_mode:'compact',compact_view:'auto'});c.hass=hass;
        const wrapper=document.createElement('div');wrapper.className='sections-slot';
        const options=c.getGridOptions(),rows=options.rows;
        wrapper.style.cssText='grid-column:span 12;min-width:0';
        if(typeof rows==='number'){
          wrapper.style.gridRow=`span ${rows}`;
          wrapper.style.height=`${rows*56+(rows-1)*8}px`;
        }
        wrapper.append(c);grid.append(wrapper);
      }
      const next=document.createElement('div');next.id='following-card';
      next.style.cssText='grid-column:span 12;height:160px;background:#009fc2';grid.append(next);
      window.resolveLayoutLyrics=(key,withLyrics=true)=>{
        const index=layoutPending.findIndex(p=>p.entity===`media_player.feiniu_${key}`);
        if(index<0)throw new Error('Expected pending lyrics');
        const {resolve}=layoutPending.splice(index,1)[0];
        resolve(withLyrics?{text:'One\nTwo\nThree',synced_lines:[{time_ms:0,text:'One'},{time_ms:4000,text:'Two'},{time_ms:8000,text:'Three'}]}:{text:'',synced_lines:[]});
      };
    });
    const cards=page.locator('feiniu-music-card');
    const measure=()=>page.evaluate(()=>{
      const cards=[...document.querySelectorAll('feiniu-music-card')];
      return cards.map((c,i)=>{
        const shell=c.shadowRoot.querySelector('.shell').getBoundingClientRect();
        const next=(cards[i+1]||document.querySelector('#following-card')).getBoundingClientRect();
        return {height:shell.height,slot:c.parentElement.getBoundingClientRect().height,gap:next.top-shell.bottom};
      });
    });
    const assertLayout=async label=>{
      const boxes=await measure();
      assert(boxes.every(b=>b.gap>=7.5&&b.slot>=b.height-.5),`${label}: ${JSON.stringify(boxes)}`);
    };
    await assertLayout('Pending lyrics stay inside their allocated slots');
    await page.evaluate(()=>resolveLayoutLyrics('a'));
    await cards.first().locator('.compact-rich').waitFor();
    await assertLayout('First auto card grows without covering the second card');
    await page.evaluate(()=>resolveLayoutLyrics('b'));
    await cards.nth(1).locator('.compact-rich').waitFor();
    for(const width of [320,520,900]){
      await page.setViewportSize({width,height:1200});
      await assertLayout('Two lyrics cards and a following card never overlap');
      assert((await measure()).every(b=>b.height===425),'Keep the existing 425px lyric layout');
    }
    // Repeated loading/no-lyrics/lyrics transitions keep the original wrappers.
    await page.evaluate(()=>{
      for(const c of document.querySelectorAll('feiniu-music-card')){
        hass.states[c._config.entity].attributes.playback_round++;c.hass=hass;
      }
    });
    await assertLayout('Auto cards shrink while the next result is pending');
    await page.evaluate(()=>{resolveLayoutLyrics('a',false);resolveLayoutLyrics('b');});
    await cards.nth(1).locator('.compact-rich').waitFor();
    await assertLayout('No-lyrics card followed by lyrics card');
    assert((await measure())[0].height<300);
    // Moving the same shell into a modal must preserve the dashboard slot.
    const before=await measure();
    await cards.nth(1).locator('#mini-open').click();
    await cards.nth(1).locator('#expanded-dialog[open]').waitFor();
    const nextTop=await page.locator('#following-card').evaluate(e=>e.getBoundingClientRect().top);
    await cards.nth(1).locator('#expanded-close button').click();
    assert.equal(await page.locator('#following-card').evaluate(e=>e.getBoundingClientRect().top),nextTop);
    assert.deepEqual(await measure(),before);
    assert.equal(await page.evaluate(()=>calls.length),0,'Layout transitions never control an output');
    assert.deepEqual(errors,[]);
    console.log('Compact Sections layout passed: two auto cards, async lyrics, loading/empty transitions, modal, 320/520/900px.');
  } finally {await context.close();}
}
