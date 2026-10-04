// Browser regression with synthetic HA messages; no NAS, HA account or real output.
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {CARD_ICONS} from './card-icons.js';
import {checkLyrics} from './lyrics-check.mjs';
import {checkCompact} from './compact-check.mjs';
import {checkCompactLyrics} from './compact-lyrics-check.mjs';
import {checkBrowse} from './browse-check.mjs';
import {checkArtistBrowse} from './artist-browse-check.mjs';
const require = createRequire(import.meta.url);
const {chromium,webkit} = require('playwright');
async function showTab(card,name){if(await card.locator('#now-back').isVisible())await card.locator('#now-back button').click();if(name==='正在播放')await card.locator('#mini-open').click();else await card.getByRole('tab',{name,exact:true}).click();}
const card = await readFile(new URL('../custom_components/feiniu_music/www/feiniu-music-card.js',import.meta.url));
let imageRequests=0;
const server = createServer((req,res)=>{
  if(req.url.startsWith('/cover.svg')){imageRequests++;res.setHeader('Content-Type','image/svg+xml');res.setHeader('Cache-Control','private, max-age=30');const i=Number(new URL(req.url,'http://localhost').searchParams.get('i'))||0;const colors=['#889c82','#9e4e62','#516a8c','#c09152','#5c4b84','#748c99','#a76142','#7d8894'];res.end(`<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 320 320"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="${colors[i%8]}"/><stop offset="1" stop-color="#171a27"/></linearGradient></defs><path fill="url(#g)" d="M0 0h320v320H0z"/><circle cx="${105+i*9}" cy="130" r="78" fill="none" stroke="#ffffff38" stroke-width="35"/><path d="M0 270L320 100V320H0Z" fill="#11111144"/><text x="25" y="275" fill="#fff" font-family="sans-serif" font-size="24" letter-spacing="3">${['AFTER RAIN','MIDNIGHT','ROOMS','SUNDAY','MOONLIGHT','DISTANCE','GOLDEN HOUR','ECHOES'][i%8]}</text><text x="26" y="298" fill="#ffffff88" font-family="sans-serif" font-size="10" letter-spacing="3">SYNTHETIC ENSEMBLE</text></svg>`);return;}
  res.setHeader('Content-Type',req.url==='/card.js'?'text/javascript; charset=utf-8':'text/html; charset=utf-8');
  res.end(req.url==='/card.js'?card:String.raw`<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;padding:10px;background:var(--primary-background-color,#f4f6f8);font-family:system-ui}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,350px),1fr));gap:16px}feiniu-music-card{min-width:0}</style></head><body><div class="grid"></div><script type="module">
  import '/card.js';
  window.calls=[];window.messages=[];window.linesDeferred=null;
  window.models={a:{revision:1,offset:0,total:3,current_id:'a-0',position:0,items:[{item_id:'a-0',track_id:'one',title:'After the rain',artist:'Synthetic ensemble',current:true},{item_id:'a-1',track_id:'two',title:'<img src=x onerror="window.injected=true">',artist:'Text, not HTML'},{item_id:'a-2',track_id:'three',title:'夜空中的回声',artist:'合成测试音乐'}],diagnostics:{phase:'playing',profile:{confirmation:'delivery',play_once:false,end_state:'idle',weak_end:false}}}};
  models.a.items.forEach((item,i)=>item.thumbnail='/cover.svg?i='+i);
  window.models.b=structuredClone(window.models.a);models.b.items.forEach(x=>x.item_id=x.item_id.replace('a','b'));models.b.current_id='b-0';
  const base='media-source://feiniu_music/account/';
  const folder=(kind,title)=>({title,media_class:'directory',media_content_id:base+kind,media_content_type:'directory',can_expand:true,can_play:false});
  const roots=[folder('track','Tracks'),folder('album','Albums'),folder('artist','Artists'),folder('playlist','Playlists')];
  const entry=(kind,id,title,i)=>({title,thumbnail:'/cover.svg?i='+i,media_class:kind,media_content_id:base+kind+'/'+id,media_content_type:kind==='track'?'music':kind,can_expand:kind!=='track',can_play:kind==='track'});
  const albums=['After the rain','Midnight sketches','Rooms / 合成音频','Sunday morning','Moonlight','The quiet distance','Golden hour','Echoes'].map((t,i)=>entry('album',String(i),t,i));
  const playlist=entry('playlist','evening','Evening playlist',3);
  const artist=entry('artist','ensemble','Synthetic ensemble',0);
  const tracks=models.a.items.map((x,i)=>({...entry('track',x.track_id,x.title,i),artist:x.artist}));
  window.fixtureBrowse=msg=>{
    const path=(msg.media_content_id||'').replace(base,'');
    if(!path)return {title:'Music library',children:roots};
    if(path==='album')return {...roots[1],children:albums};
    if(path==='artist')return {...roots[2],children:[artist,entry('artist','room','Room ensemble',1)]};
    if(path==='playlist')return {...roots[3],children:[playlist]};
    if(path==='artist/ensemble')return {...artist,children:[{...folder('artist/ensemble/tracks','Tracks')},{...folder('artist/ensemble/albums','Albums')}]};
    if(path==='artist/ensemble/albums')return {title:'Albums',children:albums.slice(0,3)};
    const context=path.startsWith('playlist/')?playlist:albums[0];
    return {...context,title:'Tracks',can_play:true,media_content_id:msg.media_content_id,children:tracks};
  };
  window.hass={language:'zh-Hans',user:{is_admin:true},states:{},callService:async(domain,service,data)=>{calls.push({domain,service,data});if(window.rejectModeService&&service==='shuffle_set')throw new Error('synthetic rejection');},callWS:async(msg)=>{
    messages.push(msg);let key=msg.entity_id.endsWith('_b')?'b':'a';
    if(msg.type==='feiniu_music/queue'){if(window.queueDeferred)return new Promise(resolve=>{window.releaseQueue=resolve;});return structuredClone(models[key]);}
    if(msg.type==='feiniu_music/lyrics'){if(linesDeferred)return new Promise(resolve=>{window.releaseLyrics=resolve;});return window.lyricFixture||{text:'A quiet room\nA familiar song',synced_lines:[{time_ms:0,text:'A quiet room'},{time_ms:4000,text:'A familiar song'}]};}
    if(msg.type==='media_player/browse_media'){if(window.failBrowse)throw {code:'unavailable'};return fixtureBrowse(msg);}
    if(msg.type==='media_player/search_media'){
      // Match HA's public WebSocket contract; permissive mocks hid a wrong key.
      if(typeof msg.search_query!=='string'||'media_search_query' in msg)throw {code:'invalid_format'};
      if(msg.search_query==='retry-once'&&!window.searchRetried){window.searchRetried=true;throw {code:'unavailable'};}
      return {result:msg.search_query==='no-match'?[]:[{title:'Search single',media_content_id:'media-source://feiniu_music/account/track/one',media_content_type:'music',can_play:true}]};
    }
    if(msg.type==='feiniu_music/edit_queue'){if(msg.revision!==models[key].revision)throw {code:'revision_conflict'};models[key].revision++;hass.states[msg.entity_id].attributes.queue_revision++;document.querySelectorAll('feiniu-music-card').forEach(c=>c.hass=hass);return {revision:models[key].revision};}
    return {saved:true};
  }};
  for(const key of ['a','b']){const id='media_player.feiniu_'+key;hass.states[id]={state:'playing',attributes:{feiniu_queue:true,friendly_name:key==='a'?'飞牛音乐 · 客厅':'飞牛音乐 · 书房',output_player:'media_player.output_'+key,queue_length:3,queue_revision:1,queue_item_id:key+'-0',playback_round:1,queue_active:true,session_phase:'playing',confirmation:'delivery',position_source:'native',supported_features:1048575,shuffle:false,repeat:'off',entity_picture:'/cover.svg?i=0',media_title:'After the rain',media_artist:'Synthetic ensemble',media_album_name:'Rooms / 合成音频',media_position:1,media_position_updated_at:new Date().toISOString(),media_duration:180,volume_level:.2}};hass.states['media_player.output_'+key]={attributes:{friendly_name:key==='a'?'客厅模拟输出':'书房模拟输出'}};const c=document.createElement('feiniu-music-card');c.setConfig({entity:id,...(new URLSearchParams(location.search).has('compact')?{display_mode:'compact'}:{})});c.hass=hass;document.querySelector('.grid').append(c);}
  </script></body></html>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await (process.env.CARD_BROWSER_ENGINE==='webkit'?webkit:chromium).launch({headless:true, ...(process.env.CARD_BROWSER_CHANNEL ? {channel:process.env.CARD_BROWSER_CHANNEL} : {})});
 await checkBrowse(browser,`http://127.0.0.1:${server.address().port}`);
 await checkArtistBrowse(browser,`http://127.0.0.1:${server.address().port}`);
 if(process.env.CARD_BROWSER_ENGINE!=='webkit'){
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});page.setDefaultTimeout(5000);page.on('console',m=>console.log('Browser:',m.type(),m.text()));page.on('requestfailed',r=>console.log('Request failed:',r.failure()?.errorText));
 await page.setViewportSize({width:390,height:844});await page.goto(`http://127.0.0.1:${server.address().port}`);
 const first=page.locator('feiniu-music-card').first(),second=page.locator('feiniu-music-card').nth(1);
 await first.locator('.tile').first().waitFor();
 assert.equal(await first.getByRole('tab',{name:'正在播放',exact:true}).count(),0,'Now playing opens through the mini player, without a duplicate navigation tab');
 await showTab(first,'播放队列');
 await showTab(second,'播放队列');
 // Reproduce HA masonry detaching/reinserting a card during its first pending read.
 await page.evaluate(async()=>{const c=document.querySelector('feiniu-music-card');window.queueDeferred=true;c._queue=null;c._key='';c.hass=hass;await Promise.resolve();const release=window.releaseQueue;c.remove();document.querySelector('.grid').prepend(c);window.queueDeferred=false;release(structuredClone(models.a));});
 await first.locator('.row').first().waitFor();
 assert.equal(await first.locator('.row').count(),3,'Reattached card must leave Loading state');
 await page.setViewportSize({width:1100,height:960});
 await page.waitForFunction(()=>[...document.querySelector('feiniu-music-card').shadowRoot.querySelectorAll('.row img')].every(img=>img.complete&&img.naturalWidth>0));
 const loadedImages=imageRequests;
 assert(await page.evaluate(async()=>{
   const c=document.querySelector('feiniu-music-card'),rows=[...c.shadowRoot.querySelectorAll('.row')],images=rows.map(r=>r.querySelector('img'));
   const mutations=[];const observer=new MutationObserver(records=>mutations.push(...records));
   images.forEach(img=>observer.observe(img,{attributes:true,attributeFilter:['src']}));
   await c._refreshQueue();await Promise.resolve();
   const stable=rows.every((r,i)=>c.shadowRoot.querySelectorAll('.row')[i]===r&&r.querySelector('img')===images[i]);
   // Same track appearing twice still has separate occurrence IDs and nodes.
   c._queue.items[1].track_id=c._queue.items[0].track_id;
   c._queue.items.reverse();c._renderContent();
   const reordered=rows.every(r=>c.shadowRoot.contains(r));
   c._queue.items.reverse();c._renderContent();await Promise.resolve();observer.disconnect();
   return stable&&reordered&&mutations.length===0;
 }),'Queue refresh/reorder must retain occurrence nodes and image src attributes');
 assert.equal(imageRequests,loadedImages,'Unchanged queue refresh must not reload images');
 // Clicking artwork targets the queue occurrence, including duplicate tracks.
 const jumpsBefore=await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/edit_queue').length);
 await first.locator('.queue-art img').nth(1).click();
 await page.waitForFunction(n=>messages.filter(m=>m.type==='feiniu_music/edit_queue').length===n+1,jumpsBefore);
 assert.deepEqual(await page.evaluate(()=>{const m=messages.filter(m=>m.type==='feiniu_music/edit_queue').at(-1);return [m.entity_id,m.action,m.item_id];}),['media_player.feiniu_a','jump','a-1']);
 await second.locator('.queue-art').nth(2).press('Enter');
 assert.deepEqual(await page.evaluate(()=>{const m=messages.filter(m=>m.type==='feiniu_music/edit_queue').at(-1);return [m.entity_id,m.action,m.item_id];}),['media_player.feiniu_b','jump','b-2']);

 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>window.injected),undefined);
 assert.equal(await first.locator('.row .name img').count(),0);
 assert.equal(await page.evaluate(()=>calls.length),0,'Rendering must not control outputs');
 await first.locator('#button-next').click();assert.equal(await page.evaluate(()=>calls.at(-1).data.entity_id),'media_player.feiniu_a');
 await showTab(second,'播放队列');await second.locator('#queue-clear').getByRole('button',{name:'停止',exact:true}).click();assert.equal(await page.evaluate(()=>calls.at(-1).data.entity_id),'media_player.feiniu_b');
 await showTab(first,'正在播放');await first.locator('#lyric-lines p').first().waitFor();
 await showTab(first,'音乐库');
 await first.locator('#mobile-categories').getByRole('button',{name:'歌单',exact:true}).click();
 await first.locator('#browse-list').getByRole('button',{name:'Evening playlist',exact:true}).click();
 await first.locator('.hero-actions').getByRole('button',{name:'播放全部',exact:true}).click();
 assert.equal(await page.evaluate(()=>calls.at(-1).data.enqueue),'replace');
 assert.equal(await page.evaluate(()=>calls.at(-1).data.media_content_id),'media-source://feiniu_music/account/playlist/evening');
 assert.equal(await first.locator('#browse-list .row img').count(),3,'Browse uses supplied HA thumbnails');
 await first.locator('#browse-list .row').first().getByRole('button',{name:'操作',exact:true}).click();
 await first.locator('#track-sheet').getByRole('button',{name:'加入队列',exact:true}).click();
 assert.equal(await page.evaluate(()=>calls.at(-1).data.enqueue),'add');
 await first.locator('#browse-list .name').first().click();
 await first.locator('#track-sheet').getByRole('button',{name:'下一首播放',exact:true}).click();
 assert.equal(await page.evaluate(()=>calls.at(-1).data.enqueue),'next');
 assert.equal(await first.locator('#track-sheet').isVisible(),false);
 // Artist subviews use the two links returned by HA and preserve parent context.
 await first.locator('#mobile-categories').getByRole('button',{name:'歌手',exact:true}).click();
 await first.locator('#browse-list').getByRole('button',{name:'Synthetic ensemble',exact:true}).click();
 assert.equal(await first.locator('#browse-list .row').count(),3);
 await first.locator('#relations').getByRole('button',{name:'专辑',exact:true}).click();
 await first.locator('#browse-list .tile').first().waitFor();
 assert.equal(await first.locator('#browse-list .tile').count(),3);
 assert.equal(await first.locator('#browse-heading h1').textContent(),'Synthetic ensemble');
 await first.locator('#browse-back button').click();
 await first.locator('#browse-list .tile').first().waitFor();
 assert.equal(await first.locator('#browse-list .tile').count(),2,'Back returns to artists, without duplicate relation history');
 await page.evaluate(()=>window.failBrowse=true);
 await first.locator('#mobile-categories').getByRole('button',{name:'歌曲',exact:true}).click();
 await first.getByRole('button',{name:'重试',exact:true}).waitFor();
 await page.evaluate(()=>window.failBrowse=false);
 await first.getByRole('button',{name:'重试',exact:true}).click();
 await first.locator('#browse-list .row').first().waitFor();
 await first.locator('#search').fill('single');await first.locator('#search').press('Enter');
 await first.locator('#browse-list').getByRole('button',{name:'Search single',exact:true}).waitFor();
 assert.equal(await first.locator('#browse-heading h1').textContent(),'single');
 assert.deepEqual(await page.evaluate(()=>messages.filter(m=>m.type==='media_player/search_media').at(-1)),{type:'media_player/search_media',entity_id:'media_player.feiniu_a',search_query:'single'});
 await first.locator('#search').fill('retry-once');await first.locator('#search').press('Enter');
 await first.locator('#browse-list').getByRole('button',{name:'重试',exact:true}).click();
 await first.locator('#browse-list').getByRole('button',{name:'Search single',exact:true}).waitFor();
 assert.equal(await first.locator('#browse-heading h1').textContent(),'retry-once');
 assert.equal(await first.locator('#browse-list').getByRole('button',{name:'重试',exact:true}).count(),0,'Successful search retry clears the error');
 await first.locator('#search').fill('no-match');await first.locator('#search').press('Enter');
 await first.locator('#browse-list').getByText('没有找到音乐。',{exact:true}).waitFor();
 assert.equal(await first.locator('#browse-list').getByRole('button',{name:'重试',exact:true}).count(),0,'No matches is a normal empty result, not a failed operation');
 await first.locator('#search').fill('single');await first.locator('#search').press('Enter');
 await first.locator('#browse-list').getByRole('button',{name:'Search single',exact:true}).waitFor();
 await showTab(first,'播放队列');
 await first.locator('#content .row').nth(1).getByRole('button',{name:'向后移动',exact:true}).click();
 assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/edit_queue').at(-1).item_id),'a-1');
 await first.getByRole('button',{name:'播放与歌词设置',exact:true}).click();await first.locator('#offset').fill('1.5');await first.getByRole('button',{name:'保存',exact:true}).click();
 assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).lyric_offset),1.5);
 assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).profile),undefined,'Lyric-only saves must not overwrite playback settings');
 // Native options update HA state without changing the queue revision.
 await page.evaluate(()=>{const a=hass.states['media_player.feiniu_a'].attributes;a.playback_profile={confirmation:'reported',end_state:'off',play_once:true,weak_end:false};document.querySelector('feiniu-music-card').hass=hass;});
 await first.getByRole('button',{name:'播放与歌词设置',exact:true}).click();
 assert.equal(await first.locator('#confirmation').inputValue(),'reported');
 assert.equal(await first.locator('#end-state').inputValue(),'off');
 assert.equal(await first.locator('#play-once').isChecked(),true);
 await first.locator('#weak-end').check();
 await first.getByRole('button',{name:'保存',exact:true}).click();
 assert.deepEqual(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).profile),{weak_end:true},'Card sends only explicitly edited profile fields');
 // Stale lyric result must not replace the next track's lyrics.
 await page.evaluate(()=>{linesDeferred=true;const c=document.querySelector('feiniu-music-card');hass.states['media_player.feiniu_a'].attributes.playback_round++;c.hass=hass;});
 await page.waitForFunction(()=>!!window.releaseLyrics);
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');const old=releaseLyrics;linesDeferred=null;hass.states['media_player.feiniu_a'].attributes.playback_round++;c.hass=hass;old({text:'STALE_SENTINEL',synced_lines:[]});});
 await showTab(first,'正在播放');
 await page.waitForFunction(()=>document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-lines').textContent.includes('quiet'));
 assert.equal(await first.locator('#lyric-lines').getByText('STALE_SENTINEL').count(),0);
 // Hidden tabs stop animation and make no queue/lyrics calls.
 const hidden=await page.evaluate(async()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));const n=messages.length;const c=document.querySelector('feiniu-music-card');c._refresh();await new Promise(r=>setTimeout(r,200));return {count:messages.length-n,raf:c._raf};});
 assert.deepEqual(hidden,{count:0,raf:0});
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));});
 await mkdir('artifacts/card-preview',{recursive:true});
 await page.evaluate(()=>{document.querySelectorAll('feiniu-music-card')[1].remove();document.querySelector('.grid').style.display='block';});
 await checkLyrics(page,first);
 await checkCompact(page);
 await checkCompactLyrics(page);
 for(const width of [360,390,430,1100,1280]){
   await page.setViewportSize({width,height:960});
   await showTab(first,'音乐库');
   const nav=width<=620?'#mobile-categories':'#categories';
   await first.locator(nav).getByRole('button',{name:'专辑',exact:true}).click();
   await first.locator('.tile').first().waitFor();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);
   assert(await first.locator('#main').evaluate(el=>el.scrollWidth<=el.clientWidth),`Card overflow at ${width}`);
   await page.screenshot({path:`artifacts/card-preview/library-${width}.png`,fullPage:true});
 }
 await first.locator('#browse-list .tile').first().click();
 await page.screenshot({path:'artifacts/card-preview/album-desktop.png',fullPage:true});
 await first.locator('#browse-list .name').first().click();
 await page.screenshot({path:'artifacts/card-preview/track-detail.png',fullPage:true});
 await page.keyboard.press('Escape');assert.equal(await first.locator('#track-sheet').isVisible(),false);
 await showTab(first,'正在播放');
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');c._lyrics=Array.from({length:35},(_,i)=>({time_ms:i*4000,text:i===0?'A quiet room':`A familiar song · ${i+1}`}));c._renderContent();});
 assert(await first.evaluate(c=>{const r=c.shadowRoot,art=r.querySelector('.now-art').getBoundingClientRect(),dock=r.querySelector('.progress').getBoundingClientRect(),view=r.querySelector('.lyric-panel').getBoundingClientRect(),lyrics=r.querySelector('#lyric-lines');return Math.abs(art.left-dock.left)<2&&lyrics.clientHeight<=view.height+1&&lyrics.scrollHeight>lyrics.clientHeight;}),'Full-player controls align with cover; long lyrics scroll inside the view');
 await page.screenshot({path:'artifacts/card-preview/now-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:960});
 await page.screenshot({path:'artifacts/card-preview/now-mobile.png',fullPage:true});
 await showTab(first,'播放队列');
 await page.screenshot({path:'artifacts/card-preview/queue-mobile.png',fullPage:true});
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');c._config.theme='light';c.hass=hass;});
 await page.screenshot({path:'artifacts/card-preview/light-390.png',fullPage:true});
 // State comes from HA, including changes made outside this card.
 await page.setViewportSize({width:1280,height:960});
 await showTab(first,'正在播放');
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');hass.states[c._config.entity].attributes.shuffle=true;hass.states[c._config.entity].attributes.repeat='off';c.hass=hass;});
 assert.equal(await first.locator('#button-mode feiniu-icon').getAttribute('icon'),'mdi:shuffle');
 assert.equal(await first.locator('#button-mode').getAttribute('aria-label'),'随机播放');
 assert.equal(await first.locator('#button-mode').evaluate(b=>getComputedStyle(b).color),await first.locator('#button-next').evaluate(b=>getComputedStyle(b).color),'Mode changes its glyph, not its colour');

 const volume=first.getByRole('button',{name:'音量',exact:true});
 assert(await volume.isVisible(),'Volume must be available in the full player');
 const vb=await volume.evaluate(b=>{const r=b.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};});
 assert(vb.x>=0&&vb.y>=0&&vb.right<=1280&&vb.bottom<=960,'Volume control must remain within the viewport');
 await volume.click();assert(await first.locator('#volume-pop').isVisible());
 await first.locator('#volume-pop').getByRole('button',{name:'关闭音量',exact:true}).click();
 assert.equal(await first.locator('#volume-pop').isVisible(),false);
 await volume.click();await page.keyboard.press('Escape');assert.equal(await first.locator('#volume-pop').isVisible(),false);
 await volume.click();await first.locator('#title').click();assert.equal(await first.locator('#volume-pop').isVisible(),false);
 await page.setViewportSize({width:390,height:960});
 assert.equal(await first.locator('.dock').evaluate(d=>getComputedStyle(d).backgroundImage),'none','Portrait controls share the artwork backdrop; no separate dark rectangle');
 await volume.click();assert(await first.locator('#volume-pop').isVisible());
 await first.locator('#volume').fill('0.37');await first.locator('#volume').dispatchEvent('change');
 assert.equal(await page.evaluate(()=>calls.at(-1).service),'volume_set');
 assert.equal(await page.evaluate(()=>calls.at(-1).data.volume_level),.37);
 await first.locator('#volume-pop').getByRole('button',{name:'关闭音量',exact:true}).click();
 // Every visible mode control reflects the same backend state in both layouts.
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');c._config.theme='dark';c.hass=hass;});
 for(const phase of ['playing','paused','idle','buffering']){
   await page.evaluate(phase=>{const c=document.querySelector('feiniu-music-card'),state=hass.states[c._config.entity];state.state=phase;state.attributes.session_phase=phase;state.attributes.session_reason='output_'+phase;c.hass=hass;},phase);
   assert.equal(await first.locator('#status').isVisible(),false,`${phase} needs no redundant badge`);
 }
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card'),state=hass.states[c._config.entity];state.attributes.session_phase='failed';state.attributes.session_reason='stream_failed';c.hass=hass;});
 assert(await first.locator('#status').isVisible(),'Actual playback failures remain visible');
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card'),state=hass.states[c._config.entity];state.state='playing';state.attributes.session_phase='playing';state.attributes.session_reason='output_reported_playing';c.hass=hass;});
 for(const width of [360,390,430,1280,1920]){
   await page.setViewportSize({width,height:width===360?740:960});
   const layout=await first.evaluate(c=>{const r=c.shadowRoot,selectors=['#button-mode','#button-previous','#button-play','#button-next','#volume-toggle'];const boxes=selectors.map(s=>r.querySelector(s).getBoundingClientRect());return {centres:boxes.map(b=>b.y+b.height/2),separated:boxes.every((b,i)=>i===0||b.left>=boxes[i-1].right-1),cover:r.querySelector('.now-art').getBoundingClientRect().width,artistY:r.querySelector('#artist').getBoundingClientRect().top,albumY:r.querySelector('#album').getBoundingClientRect().top};});
   assert(Math.max(...layout.centres)-Math.min(...layout.centres)<1,'All five controls share one row');
   assert(layout.separated,`Controls do not overlap at ${width}px`);
   assert(layout.cover<=480,'The cover stays within the measured desktop maximum');
   assert.equal(layout.artistY,layout.albumY,'Artist and album share a compact metadata line');
   if(width>700)assert(await first.evaluate(c=>{const r=c.shadowRoot,gap=r.querySelector('.progress').getBoundingClientRect().top-r.querySelector('.now-meta').getBoundingClientRect().bottom;return gap>12&&gap<65;}),'Desktop progress stays close to song metadata, without an empty lower row');
   assert(await first.locator('.now-info').evaluate(el=>Number(getComputedStyle(el).zIndex)>0),'Artwork and metadata stay above the ambient background');
   assert.equal(await first.locator('#button-mode').evaluate(b=>getComputedStyle(b).color),await first.locator('#button-next').evaluate(b=>getComputedStyle(b).color),'Dark theme modes keep the same foreground colour');
   const bounds=await volume.evaluate(b=>{const r=b.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};});
   assert(bounds.x>=0&&bounds.y>=0&&bounds.right<=width&&bounds.bottom<=(width===360?740:960));
   await volume.click();
   assert(await first.locator('#volume-pop').evaluate(el=>{const r=el.getBoundingClientRect();return r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;}),'Volume popup fits the viewport');
   await page.screenshot({path:`artifacts/card-preview/player-volume-${width}.png`,fullPage:true});
   await first.locator('#volume-pop').getByRole('button',{name:'关闭音量',exact:true}).click();
 }
 // Measure the complete content group, not only the cover or button row.
 // Official desktop reference: 480px cover, 496px left column, 64px gap, 520px lyrics.
 for(const size of [{width:740,height:960},{width:1024,height:720},{width:1280,height:720},{width:1920,height:1080},{width:2560,height:1280}]){
   await page.setViewportSize(size);
   const layout=await first.evaluate(c=>{const r=c.shadowRoot,box=s=>r.querySelector(s).getBoundingClientRect(),shell=box('.shell'),cover=box('.now-art'),dock=box('.dock'),lyrics=box('.lyric-panel'),progress=box('.progress');return {shellX:shell.x,shellW:shell.width,shellY:shell.y,shellH:shell.height,coverX:cover.x,coverY:cover.y,coverW:cover.width,left:dock.left,right:lyrics.right,lyricsW:lyrics.width,gap:lyrics.left-dock.right,bottom:dock.bottom,progressX:progress.x,progressW:progress.width};});
   assert(Math.abs((layout.left+layout.right)/2-(layout.shellX+layout.shellW/2))<1,`Cover and lyrics are centred as a group at ${size.width}px`);
   assert(layout.left>=layout.shellX+32&&layout.right<=layout.shellX+layout.shellW-32,'Both columns fit inside the card');
   assert(layout.coverY>=layout.shellY&&layout.bottom<=layout.shellY+layout.shellH,'The complete playback column fits vertically');
   assert(Math.abs(layout.progressX-layout.coverX)<1&&Math.abs(layout.progressW-layout.coverW)<1,'Metadata/cover and progress share the same width');
   if(size.width>=1920){assert.equal(layout.coverW,480);assert.equal(layout.lyricsW,520);assert.equal(layout.gap,64);assert.equal(layout.right-layout.left,1080);}
   await page.screenshot({path:`artifacts/card-preview/player-centred-${size.width}.png`,fullPage:true});
 }
 for(const width of [1024,1280]){
   await page.setViewportSize({width,height:720});
   assert(await first.evaluate(c=>{const r=c.shadowRoot;return r.getElementById('album').getBoundingClientRect().bottom+12<r.querySelector('.progress').getBoundingClientRect().top;}),'Short desktop windows keep song metadata above the seek bar');
   assert(await first.evaluate(c=>{const shell=c.shadowRoot.querySelector('.shell');shell.scrollTop=97;return shell.scrollTop===0;}),'The full-player shell must not scroll or clip its cover when controls receive focus');
   assert(await first.evaluate(c=>{const r=c.shadowRoot;return r.querySelector('.now-art').getBoundingClientRect().top>=r.querySelector('.shell').getBoundingClientRect().top;}),'Cover stays below the top of the full-player surface');
   await page.screenshot({path:`artifacts/card-preview/player-short-${width}.png`,fullPage:true});
 }
 await page.setViewportSize({width:1280,height:960});
 await showTab(first,'音乐库');
 const modes=[
   {shuffle:false,repeat:'off',icon:'sequence',label:'顺序播放',calls:[['shuffle_set',{shuffle:true}]]},
   {shuffle:true,repeat:'off',icon:'shuffle',label:'随机播放',calls:[['shuffle_set',{shuffle:false}],['repeat_set',{repeat:'all'}]]},
   {shuffle:false,repeat:'all',icon:'repeat',label:'列表循环',calls:[['repeat_set',{repeat:'one'}]]},
   {shuffle:false,repeat:'one',icon:'repeat-one',label:'单曲循环',calls:[['repeat_set',{repeat:'off'}]]},
 ];
 for(const mode of modes){
   await page.evaluate(m=>{const c=document.querySelector('feiniu-music-card');Object.assign(hass.states[c._config.entity].attributes,{shuffle:m.shuffle,repeat:m.repeat});c.hass=hass;calls.length=0;},mode);
   for(const selector of ['#button-mode','#dock-tools [data-mode]']){
     assert.equal(await first.locator(selector+' feiniu-icon').getAttribute('icon'),'mdi:'+mode.icon);
     assert.equal(await first.locator(selector).getAttribute('aria-label'),mode.label);
   }
   await first.locator('#dock-tools [data-mode]').click();
   await page.waitForFunction(()=>!document.querySelector('feiniu-music-card')._modePending);
   assert.deepEqual(await page.evaluate(()=>calls.map(c=>[c.service,Object.fromEntries(Object.entries(c.data).filter(([k])=>k!=='entity_id'))])),mode.calls);
   // A service reply does not replace HA's authoritative state.
   assert.equal(await first.locator('#dock-tools [data-mode] feiniu-icon').getAttribute('icon'),'mdi:'+mode.icon);
 }
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');Object.assign(hass.states[c._config.entity].attributes,{shuffle:true,repeat:'off'});c.hass=hass;calls.length=0;window.rejectModeService=true;});
 await first.locator('#dock-tools [data-mode]').click();await page.waitForFunction(()=>!document.querySelector('feiniu-music-card')._modePending);
 assert.equal(await page.evaluate(()=>calls.length),1,'If disabling shuffle fails, do not send a repeat command');
 assert.equal(await first.locator('#dock-tools [data-mode] feiniu-icon').getAttribute('icon'),'mdi:shuffle');
 assert(await first.locator('#error').isVisible());
 await page.evaluate(()=>{window.rejectModeService=false;});
 await volume.click();await first.locator('#mini-open').click();assert.equal(await first.locator('#volume-pop').isVisible(),false,'Changing view dismisses the popup');
 const beforePanel=await page.evaluate(()=>calls.length);
 await first.locator('#now-queue').click();
 assert(await first.locator('#queue-view').isVisible());assert(await first.locator('#now-view').isVisible());
 assert(await first.locator('#queue-view').evaluate(e=>{const b=e.getBoundingClientRect(),s=e.getRootNode().querySelector('.shell').getBoundingClientRect();return Math.abs(s.right-b.right-16)<1&&b.width<=400;}),'Queue opens at the right edge of the full player');
 await page.screenshot({path:'artifacts/card-preview/now-queue-desktop.png',fullPage:true});
 await first.locator('#queue-close button').click();assert.equal(await first.locator('#queue-view').isVisible(),false);
 await first.locator('#now-queue').click();await page.keyboard.press('Escape');assert.equal(await first.locator('#queue-view').isVisible(),false);
 await first.locator('#now-queue').click();await first.locator('#title').click();assert.equal(await first.locator('#queue-view').isVisible(),false);
 assert.equal(await page.evaluate(()=>calls.length),beforePanel,'Queue open/close sends no playback commands');
 // Visible geometry follows the reference hierarchy, independent of SVG viewBox whitespace.
 for(const mode of modes){
   await page.evaluate(m=>{const c=document.querySelector('feiniu-music-card');Object.assign(hass.states[c._config.entity].attributes,{shuffle:m.shuffle,repeat:m.repeat});c.hass=hass;},mode);
   const heights=await first.evaluate(c=>['button-mode','button-previous','button-play','button-next','volume-toggle'].map(id=>{const svg=c.shadowRoot.getElementById(id).querySelector('feiniu-icon').shadowRoot.querySelector('svg');return svg.getBBox().height*svg.getBoundingClientRect().height/24;}));
   assert(heights[2]>heights[1]&&heights[1]>heights[0]&&Math.abs(heights[0]-heights[4])<3,`Play is tallest, skips next, mode and volume balanced: ${mode.icon} ${JSON.stringify(heights)}`);
 }
 // Artwork is actionable throughout browsing, including placeholder art in search.
 for(const category of ['歌曲','专辑','歌手','歌单']){
   await showTab(first,'音乐库');
   await first.locator('#categories').getByRole('button',{name:category,exact:true}).click();
   if(category!=='歌曲')await first.locator('#browse-list .tile-art').first().click();
   await first.locator('#browse-list .row-cover img').first().waitFor();
   const before=await page.evaluate(()=>calls.length);
   await first.locator('#browse-list .row-cover img').first().click();
   assert.equal(await page.evaluate(()=>calls.length),before+1,`${category}: cover sends exactly one play command`);
   assert.deepEqual(await page.evaluate(()=>calls.at(-1)),{domain:'media_player',service:'play_media',data:{entity_id:'media_player.feiniu_a',media_content_type:'music',media_content_id:'media-source://feiniu_music/account/track/one',enqueue:'replace'}});
   assert.equal(await first.locator('#track-sheet').isVisible(),false,'Cover plays directly without opening a details dialog');
 }
 await first.locator('#search').fill('single');await first.locator('#search').press('Enter');
 await first.locator('#browse-list .row-cover').waitFor();
 assert.equal(await first.locator('#browse-list .row-cover img').count(),0,'Search fixture exercises placeholder art');
 const beforeSearch=await page.evaluate(()=>calls.length);
 await first.locator('#browse-list .row-cover').press('Enter');
 assert.equal(await page.evaluate(()=>calls.length),beforeSearch+1);
 assert.equal(await page.evaluate(()=>calls.at(-1).data.media_content_id),'media-source://feiniu_music/account/track/one');
 await showTab(first,'正在播放');
 await first.locator('#now-queue').click();
 const beforeSidebar=await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/edit_queue').length);
 await first.locator('#queue-view .queue-art img').first().click();
 assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/edit_queue').length),beforeSidebar+1);
 assert.equal(await first.locator('#queue-view').isVisible(),true,'Playing queue artwork retains the right panel');
 await first.locator('#queue-close button').click();
 // Real Fullscreen API, including nested shadow DOM like HA and explicit card height.
 const beforeFullscreen=await page.evaluate(()=>calls.length);
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card'),host=document.createElement('div');document.querySelector('.grid').append(host);host.attachShadow({mode:'open'}).append(c);c.setConfig({entity:'media_player.feiniu_a',height:650});c.hass=hass;});
 await showTab(first,'正在播放');
 const fullscreen=first.locator('#now-fullscreen');
 assert(await fullscreen.isVisible());
 assert(await fullscreen.isEnabled());
 const normal=await first.locator('.shell').boundingBox();
 await fullscreen.click();
 await page.waitForFunction(()=>{const host=document.querySelector('.grid>div');return !!host?.shadowRoot.fullscreenElement;});
 assert.equal(await fullscreen.getAttribute('aria-label'),'退出全屏');
 assert.equal(await fullscreen.locator('feiniu-icon').getAttribute('icon'),'mdi:fullscreen-exit');
 assert(await first.evaluate(c=>{const b=c.shadowRoot.querySelector('.shell').getBoundingClientRect();return b.x===0&&b.y===0&&Math.abs(b.width-innerWidth)<1&&Math.abs(b.height-innerHeight)<1;}),'Fullscreen fills the viewport and ignores configured card height');
 await page.screenshot({path:'artifacts/card-preview/player-fullscreen.png',fullPage:true});
 await fullscreen.click();
 await page.waitForFunction(()=>!document.fullscreenElement);
 assert.equal(await fullscreen.getAttribute('aria-label'),'全屏');
 assert.equal((await first.locator('.shell').boundingBox()).height,normal.height);
 await fullscreen.click();
 await page.waitForFunction(()=>!!document.fullscreenElement);
 await page.evaluate(()=>document.exitFullscreen());
 await page.waitForFunction(()=>{const c=document.querySelector('.grid>div').shadowRoot.querySelector('feiniu-music-card');return !document.fullscreenElement&&c.shadowRoot.querySelector('#now-fullscreen').getAttribute('aria-pressed')==='false';});
 assert.equal(await fullscreen.getAttribute('aria-pressed'),'false','Browser-initiated exit updates the control');
 await fullscreen.click();await page.waitForFunction(()=>!!document.fullscreenElement);
 await first.locator('#now-back button').click();
 await page.waitForFunction(()=>!document.fullscreenElement);
 assert.equal(await fullscreen.isVisible(),false,'Leaving the player also exits fullscreen');
 assert.equal(await page.evaluate(()=>calls.length),beforeFullscreen,'Fullscreen never controls audio');
 await page.evaluate(()=>{const host=document.querySelector('.grid>div'),c=host.shadowRoot.querySelector('feiniu-music-card');document.querySelector('.grid').prepend(c);host.remove();c.setConfig({entity:'media_player.feiniu_a'});c.hass=hass;});
 await showTab(first,'正在播放');
 await page.setViewportSize({width:390,height:844});
 assert.equal(await fullscreen.isVisible(),false,'Normal portrait keeps the existing queue entry at top right');
 await page.setViewportSize({width:1280,height:960});
 // Reconfiguration resets account-bound navigation as well as queue data.
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');c.setConfig({entity:'media_player.feiniu_b'});c.hass=hass;});
 await page.waitForFunction(()=>document.querySelector('feiniu-music-card')._queue?.current_id==='b-0');
 assert.equal(await page.evaluate(()=>document.querySelector('feiniu-music-card')._offset),0);
 // Render the actual component, rather than a second copy of the SVG renderer.
 await page.setViewportSize({width:1280,height:1100});
 const geometry=await page.evaluate(names=>{
   document.querySelector('.grid').remove();
   document.body.style.cssText='margin:0;padding:32px;background:#eeedf2;color:#23202e;font-family:system-ui';
   const title=document.createElement('h1');title.textContent='FeiNiu card · hand-drawn UI icons';title.style.cssText='font-size:26px;margin:0 0 8px';document.body.append(title);
   const note=document.createElement('p');note.textContent='One SVG per symbol · 16 / 24 / 32 px · dark and light backgrounds';note.style.cssText='margin:0 0 24px;color:#696574';document.body.append(note);
   const grid=document.createElement('div');grid.style.cssText='display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px';document.body.append(grid);
   const boxes=[];
   for(const name of names){
     const tile=document.createElement('section');tile.style.cssText='overflow:hidden;border-radius:12px;background:white';grid.append(tile);
     for(const dark of [true,false]){
       const row=document.createElement('div');row.style.cssText=`display:flex;align-items:center;justify-content:space-evenly;height:64px;background:${dark?'#272330':'#fff'};color:${dark?'#f8f6fc':'#302937'}`;tile.append(row);
       for(const size of [16,24,32]){
         const icon=document.createElement('feiniu-icon');icon.setAttribute('icon',name);icon.style.setProperty('--mdc-icon-size',`${size}px`);row.append(icon);
         const svg=icon.shadowRoot.querySelector('svg'),box=svg.getBBox();boxes.push({name,size,x:box.x,y:box.y,right:box.x+box.width,bottom:box.y+box.height,paths:svg.querySelectorAll('path').length,ns:svg.namespaceURI,color:getComputedStyle(svg).stroke});
       }
     }
     const label=document.createElement('div');label.textContent=name;label.style.cssText='padding:3px 8px 12px;text-align:center;font-size:12px;color:#77717d';tile.append(label);
   }
   return boxes;
 },Object.keys(CARD_ICONS));
 for(const box of geometry){
   assert(box.paths>0&&box.ns==='http://www.w3.org/2000/svg',`${box.name} SVG paths`);
   assert(box.x>=1&&box.y>=1&&box.right<=23&&box.bottom<=23,`${box.name} has room for its stroke`);
   assert(['rgb(248, 246, 252)','rgb(48, 41, 55)'].includes(box.color),`${box.name} inherits theme color`);
 }
 await page.screenshot({path:'artifacts/card-preview/ui-icons.png',fullPage:true});
 assert.deepEqual(errors,[]);
 console.log(`Browser checks passed: library/detail/artist tabs/search/back/retry, queue and actions, 2 isolated cards, stable thumbnails, lyrics, dialogs, 360/390/430/1100/1280px, dark/light; ${Object.keys(CARD_ICONS).length} UI icons at 16/24/32px.`);
 }
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
