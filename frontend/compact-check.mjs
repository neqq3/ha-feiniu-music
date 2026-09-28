import assert from 'node:assert/strict';

export async function checkCompact(sourcePage){
  const context=await sourcePage.context().browser().newContext(),page=await context.newPage(),errors=[];
  page.on('pageerror',err=>errors.push(err.message));page.setDefaultTimeout(5000);
  try{
    await page.setViewportSize({width:1000,height:900});await page.goto(`${sourcePage.url()}?compact=1`);
    const first=page.locator('feiniu-music-card').first(),second=page.locator('feiniu-music-card').nth(1);
    await first.locator('#mini-open').waitFor();
    assert.deepEqual(await page.evaluate(()=>messages),[],'Collapsed dashboard cards do not load the library, queue pages or lyrics');
    assert(await first.evaluate(c=>c.getCardSize()===5&&c.getGridOptions().rows===5));
    assert.deepEqual(await first.evaluate(c=>c.constructor.getStubConfig(hass)),{entity:'media_player.feiniu_a',display_mode:'compact',compact_view:'auto',compact_background:'artwork',theme:'dark'});
    const initial=await first.boundingBox();assert(initial.height<300&&initial.height>180,'Compact card has content-sized height');
    assert.equal(await first.locator('.compact-heading>feiniu-icon').count(),0,'The compact title has no leading music-note icon');
    assert.equal(await first.locator('.shell').evaluate(e=>getComputedStyle(e).backdropFilter),'none','Existing compact YAML keeps the original background and opacity');
    assert.equal(await first.locator('.compact-background img[src]').count(),0,'Original background does not load decorative artwork');
    const layout=await first.evaluate(c=>{const root=c.shadowRoot,get=id=>root.getElementById(id).getBoundingClientRect();return {progress:get('seek').y,buttons:get('controls').bottom,tools:get('dock-tools').y,controls:get('controls').y,playIcon:getComputedStyle(root.querySelector('#button-play feiniu-icon')).getPropertyValue('--mdc-icon-size').trim()};});
    assert(layout.progress>layout.buttons&&Math.abs(layout.tools-layout.controls)<8,'Original compact controls stay in one row with progress below');
    assert.equal(layout.playIcon,'28px','Keep the established compact play/pause size');
    await page.evaluate(()=>{hass.states['media_player.feiniu_b'].attributes.entity_picture='/cover.svg?i=1';document.querySelectorAll('feiniu-music-card').forEach(c=>{c.setConfig({...c._config,compact_background:'artwork'});c.hass=hass;});});
    await page.waitForFunction(()=>[...document.querySelectorAll('feiniu-music-card')].every(c=>{const img=c.shadowRoot.querySelector('.compact-background img.visible');return img?.naturalWidth>0&&Number(getComputedStyle(img).opacity)>.71;}));
    await page.screenshot({path:'artifacts/card-preview/compact-dashboard.png',fullPage:true});
    await first.locator('#button-next').click();
    assert.deepEqual(await page.evaluate(()=>calls),[{domain:'media_player',service:'media_next_track',data:{entity_id:'media_player.feiniu_a'}}]);
    await first.locator('#volume-toggle').click();assert(await first.locator('#volume-pop').isVisible());
    await first.locator('#volume-close button').click();
    const beforeOpen=await page.evaluate(()=>calls.length);
    await first.locator('#mini-open').click();
    await first.locator('#expanded-dialog[open]').waitFor();
    await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._lyrics.length>0);
    assert(await first.locator('#expanded-dialog').evaluate(e=>e.matches(':modal')),'Expansion uses a real modal with focus containment');
    assert((await first.locator('.shell').boundingBox()).width>900,'Expansion is independent of dashboard column width');
    const dialogBounds=await first.locator('#expanded-dialog').boundingBox(),closeBounds=await first.locator('#expanded-close button').boundingBox();
    assert(dialogBounds.x+dialogBounds.width-closeBounds.x-closeBounds.width<24,'Close control stays at the right edge of the expanded view');
    assert.equal(Math.round((await first.boundingBox()).height),Math.round(initial.height),'The dashboard keeps its original card space while expanded');
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='media_player/browse_media').length),0,'Opening lyrics does not read the music library');
    await page.keyboard.press('Escape');await first.locator('#expanded-dialog[open]').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(()=>calls.length),beforeOpen,'Open/close never changes playback');
    assert.equal(await first.locator('#mini-open').evaluate(e=>e===e.getRootNode().activeElement),true,'Closing returns keyboard focus to its opener');
    assert.equal(Math.round((await first.boundingBox()).height),Math.round(initial.height));
    await first.locator('#dock-tools .queue-toggle').click();await first.locator('.queue-row').first().waitFor();
    assert.equal(await first.locator('.queue-row').count(),3);await first.locator('#expanded-close button').click();
    await first.locator('#compact-open button').click();await first.locator('.tile').first().waitFor();
    assert(await first.locator('#browser').isVisible());
    for(const width of [1000,390]){
      await page.setViewportSize({width,height:900});
      const nav=first.locator(width===1000?'#categories':'#mobile-categories');
      for(const category of ['歌曲','专辑','歌手','歌单']){
        await nav.getByRole('button',{name:category,exact:true}).click();
        await nav.locator('.active').filter({hasText:category}).waitFor();
        assert.equal(await nav.locator('[aria-current="page"]').count(),1);
        await first.getByRole('tab',{name:'播放队列',exact:true}).click();
        assert.equal(await first.locator('[data-browse-root].active,[data-browse-root][aria-current]').count(),0,'Queue clears both desktop and portrait category highlights');
        assert.equal(await first.getByRole('tab',{name:'播放队列',exact:true}).getAttribute('aria-selected'),'true');
        assert.equal(await first.locator('#mobile-categories').isVisible(),false,'Portrait queue does not show music library category buttons');
        await first.getByRole('tab',{name:'音乐库',exact:true}).click();
        assert.equal(await nav.locator('.active').textContent(),category,'Returning to the library restores its remembered category');
      }
    }
    await page.setViewportSize({width:1000,height:900});await first.locator('#expanded-close button').click();
    await first.locator('#mini-open').click();await first.locator('#now-fullscreen').click();
    await page.waitForFunction(()=>!!document.fullscreenElement);
    await first.locator('#expanded-close button').click();await page.waitForFunction(()=>!document.fullscreenElement);
    assert.equal(await first.locator('#expanded-dialog').getAttribute('open'),null);
    assert.equal(await page.evaluate(()=>calls.length),beforeOpen);
    await second.locator('#button-next').click();
    assert.equal(await page.evaluate(()=>calls.at(-1).data.entity_id),'media_player.feiniu_b','Second card retains its independent target after the modal closes');
    for(const width of [320,390,700]){
      await page.setViewportSize({width,height:844});
      await page.evaluate(()=>{document.querySelectorAll('feiniu-music-card')[1].hidden=true;document.querySelector('.grid').style.display='block';});
      assert(await first.evaluate(c=>c.shadowRoot.querySelector('.shell').scrollWidth<=c.clientWidth+1),'Compact card does not overflow a narrow dashboard');
      assert((await first.boundingBox()).height<320);
      await page.screenshot({path:`artifacts/card-preview/compact-${width}.png`,fullPage:true});
    }
    await first.locator('#mini-open').click();
    await first.evaluate(c=>{c.setConfig({entity:'media_player.feiniu_b',display_mode:'compact'});c.hass=hass;});
    assert.equal(await first.locator('#expanded-dialog[open]').count(),0,'Reconfiguration closes stale account-bound dialogs');
    assert.equal(await first.evaluate(c=>c.style.minHeight),'');
    // Editor contract: use HA form schema/events, preserve YAML extensions, no player actions.
    const beforeEditor=await page.evaluate(()=>calls.length);
    const result=await page.evaluate(()=>{
      const Card=customElements.get('feiniu-music-card'),editor=Card.getConfigElement();document.body.append(editor);
      const changes=[];editor.addEventListener('config-changed',e=>changes.push({value:e.detail.config,bubbles:e.bubbles,composed:e.composed}));
      const config={type:'custom:feiniu-music-card',entity:'media_player.feiniu_a',future_option:{keep:true},grid_options:{columns:12}};
      editor.setConfig(config);editor.hass=hass;const form=editor.shadowRoot.querySelector('ha-form');
      const initialMode=form.data.display_mode,entities=form.schema[0].selector.entity.include_entities;
      form.dispatchEvent(new CustomEvent('value-changed',{detail:{value:{...form.data,display_mode:'compact',title:'客厅音乐',theme:'auto'}},bubbles:true,composed:true}));
      const compactHeightField=form.schema.some(s=>s.name==='height');
      form.dispatchEvent(new CustomEvent('value-changed',{detail:{value:{...form.data,display_mode:'full',height:700}},bubbles:true,composed:true}));
      const fullHeightField=form.schema.some(s=>s.name==='height');
      form.dispatchEvent(new CustomEvent('value-changed',{detail:{value:{...form.data,title:'',height:undefined}},bubbles:true,composed:true}));
      editor.hass={...hass,language:'en'};const label=form.computeLabel({name:'entity'});
      editor.remove();return {changes,initialMode,entities,compactHeightField,fullHeightField,label,original:config};
    });
    assert.equal(result.initialMode,'full','Legacy YAML retains full mode');
    assert.deepEqual(result.entities,['media_player.feiniu_a','media_player.feiniu_b'],'Selector excludes underlying non-FeiNiu players');
    assert.equal(result.changes.length,3,'setConfig/state updates never emit spurious config changes');
    for(const e of result.changes){assert(e.bubbles&&e.composed);assert.deepEqual(e.value.future_option,{keep:true});assert.deepEqual(e.value.grid_options,{columns:12});}
    assert(!result.compactHeightField&&result.fullHeightField);
    assert.equal(result.label,'FeiNiu player');assert(!('title' in result.changes.at(-1).value));assert(!('height' in result.changes.at(-1).value));
    assert(!('display_mode' in result.original),'Editor does not mutate HA-owned configuration');
    assert.equal(await page.evaluate(()=>calls.length),beforeEditor,'Editing appearance sends no playback commands');
    assert.deepEqual(errors,[]);
  }finally{await context.close();}
}
