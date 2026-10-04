// Real component/DOM checks against deferred synthetic HA WebSocket replies.
import assert from 'node:assert/strict';

export async function checkBrowse(browser,url){
 const page=await browser.newPage({viewport:{width:1280,height:800},...(process.env.CARD_BROWSER_ENGINE==='webkit'?{isMobile:true,hasTouch:true}: {})});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(url);const card=page.locator('feiniu-music-card').first();
  await card.locator('.tile').first().waitFor();
  assert(await page.evaluate(()=>messages.findIndex(m=>m.media_content_id?.endsWith('/album'))<messages.findIndex(m=>m.media_content_id?.endsWith('/playlist'))),'Main album read must precede optional sidebar work');
  await page.evaluate(()=>{
   window.card=document.querySelector('feiniu-music-card');window.originalWS=hass.callWS;
   window.pending=[];window.deferKind='';
   hass.callWS=msg=>msg.type==='media_player/browse_media'&&msg.media_content_id?.endsWith('/'+window.deferKind)&&window.deferKind
    ?new Promise((resolve,reject)=>pending.push({msg,resolve,reject})):originalWS(msg);
   window.deferKind='playlist';card._playlistRows=null;card._loadPlaylists();card._loadPlaylists();
  });
  assert.equal(await page.evaluate(()=>pending.length),1,'Repeated sidebar demand is deduplicated');
  await page.evaluate(()=>card._browse(card._roots.find(x=>x.title==='Albums')));
  assert(await card.locator('.tile').count()>0,'Album text/tiles render while sidebar is unresolved');
  await page.evaluate(()=>{pending.pop().resolve({children:[]});window.deferKind='track';card._browse(card._roots.find(x=>x.title==='Tracks'));});
  assert.equal(await card.locator('#browse-heading h1').textContent(),'歌曲');
  assert.equal(await card.locator('#browse-heading .muted').count(),0,'Loading clears the old count');
  await page.evaluate(()=>card._browse(card._roots.find(x=>x.title==='Artists')));
  await page.evaluate(()=>{pending.pop().resolve({title:'OLD TEST',children:[]});});
  assert.equal(await card.locator('#browse-heading h1').textContent(),'歌手','Late reply cannot replace newer navigation');
  // Explicit timeout releases the UI and permits retry; standard WS may finish later.
  await page.clock.install();
  await page.evaluate(()=>{card._browse(card._roots.find(x=>x.title==='Tracks'));});
  await page.clock.fastForward(96000);
  await card.locator('#browse-list').getByRole('button',{name:'重试',exact:true}).waitFor();
  const count=await page.evaluate(()=>{const n=pending.length;for(let i=0;i<20;i++)card.hass=hass;return n;});
  assert.equal(await page.evaluate(()=>pending.length),count,'hass updates do not create retry storms');
  await page.evaluate(()=>{window.deferKind='';});
  await card.locator('#browse-list').getByRole('button',{name:'重试',exact:true}).click();
  await card.locator('#browse-list .row').first().waitFor();
  await page.evaluate(()=>{pending.pop().resolve({title:'STALE TEST',children:[]});});
  assert(await card.locator('#browse-list .row').count()>0);
  // A failed WS call must remain retryable after reconnection, without reattaching.
  await page.evaluate(()=>{
   hass.callWS=msg=>msg.type==='media_player/browse_media'?Promise.reject(new Error('test disconnected')):originalWS(msg);
   return card._browse(card._roots.find(x=>x.title==='Albums'));
  });
  await card.locator('#browse-list').getByRole('button',{name:'重试',exact:true}).waitFor();
  await page.evaluate(()=>{hass.callWS=originalWS;card.hass=hass;});
  await card.locator('#browse-list').getByRole('button',{name:'重试',exact:true}).click();
  await card.locator('.tile').first().waitFor();
  // A pending old-account reply cannot populate the newly configured account.
  await page.evaluate(()=>{
   hass.callWS=msg=>msg.type==='media_player/browse_media'&&msg.media_content_id?.endsWith('/track')?new Promise(resolve=>{window.accountReply=resolve;}):originalWS(msg);
   card._browse(card._roots.find(x=>x.title==='Tracks'));
   card.setConfig({entity:'media_player.feiniu_b',display_mode:'full'});
   accountReply({title:'OLD ACCOUNT TEST',children:[]});
  });
  await card.locator('.tile').first().waitFor();
  assert.equal(await page.evaluate(()=>card._config.entity),'media_player.feiniu_b');
  assert.equal(await card.locator('#browse-heading h1').textContent(),'专辑');
  // Keep a real image request unresolved while the useful list is already visible.
  const covers=[];await page.route('**/test-slow-cover',route=>{covers.push(route);});
  await Promise.all([page.waitForRequest('**/test-slow-cover'),page.evaluate(()=>{
   hass.callWS=msg=>msg.type==='media_player/browse_media'&&msg.media_content_id?.endsWith('/album')
    ?Promise.resolve({title:'Albums',children:[{title:'test cover pending',media_class:'album',media_content_type:'album',media_content_id:'test',can_expand:true,thumbnail:location.origin+'/test-slow-cover'}]}):originalWS(msg);
   return card._browse(card._roots.find(x=>x.title==='Albums'));
  })]);
  assert.equal(await card.locator('.tile-title').textContent(),'test cover pending');
  assert.equal(await card.locator('.tile img').evaluate(img=>img.complete),false);
  for(const route of covers)await route.fulfill({status:204});
  await page.unroute('**/test-slow-cover');
  // Backend-supplied page links stay separate from cards/tracks and keep global row numbers.
  await page.evaluate(()=>{
   const base=card._roots.find(x=>x.title==='Tracks').media_content_id;
   window.deferKind='';hass.callWS=msg=>{
    if(msg.type!=='media_player/browse_media'||!msg.media_content_id?.includes('/track'))return originalWS(msg);
    const second=msg.media_content_id.includes('/page/2/100');
    const start=second?100:0,total=102;
    const children=Array.from({length:second?2:100},(_,i)=>({title:'test '+(start+i),media_class:'track',media_content_id:base+'/queue/'+(start+i)+'/test-'+(start+i),media_content_type:'music',can_play:true,can_expand:false}));
    children.push({title:second?'Previous page':'Next page',media_class:'directory',media_content_type:'feiniu_page',media_content_id:base+'/page/'+(second?1:2)+'/100',can_expand:true,can_play:false});
    return Promise.resolve({title:'Tracks',media_content_id:base,media_content_type:'music',children,feiniu_paging:{offset:start,size:100,total,context_id:base}});
   };
   return card._browse(card._roots.find(x=>x.title==='Tracks'));
  });
  assert.equal(await card.locator('#browse-list .row').count(),100);
  await card.locator('#browse-list .pager button').click();
  assert.equal(await card.locator('#browse-list .row').count(),2);
  assert.equal(await card.locator('#browse-list .number').first().textContent(),'101');
  await card.locator('#browse-heading').getByRole('button',{name:'播放全部',exact:true}).click();
  assert((await page.evaluate(()=>calls.at(-1).data.media_content_id)).endsWith('/track'));
  // Detach/reinsert while browsing must recover with a new request, without a sticky spinner.
  await page.evaluate(()=>{
   hass.callWS=msg=>msg.type==='media_player/browse_media'&&msg.media_content_id?.endsWith('/artist')?new Promise(resolve=>{window.detachedReply=resolve;}):originalWS(msg);
   card._browse(card._roots.find(x=>x.title==='Artists'));card.remove();document.querySelector('.grid').prepend(card);
   detachedReply({title:'DETACHED TEST',children:[]});
  });
  await card.locator('.tile').first().waitFor();
  // Emulate a narrow touch viewport; this is not a physical iOS-device assertion.
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>{hass.callWS=originalWS;card.setConfig({entity:'media_player.feiniu_b',display_mode:'compact'});card._openExpanded();return card._showTab('browse');});
  await card.locator('.tile').first().waitFor();
  await page.evaluate(()=>{
   hass.callWS=msg=>msg.type==='media_player/browse_media'&&msg.media_content_id?.endsWith('/track')?new Promise(resolve=>{window.modalReply=resolve;}):originalWS(msg);
   card._browse(card._roots.find(x=>x.title==='Tracks'));card._finishExpanded();modalReply({title:'CLOSED TEST',children:[]});
  });
  assert.equal(await page.evaluate(()=>card._browseResult),null,'Closing dialog discards its late reply');
  await page.evaluate(()=>{hass.callWS=originalWS;card._openExpanded();return card._showTab('browse');});
  await card.locator('.tile').first().waitFor();
  assert.deepEqual(errors,[]);
  console.log('Browse lifecycle passed: slow sidebar/images, stale navigation/account replies, disconnect and timeout/retry, page links/global positions, detach/reattach, touch dialog close/reopen.');
 }finally{await page.close();}
}
