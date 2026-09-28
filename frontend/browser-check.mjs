// Browser regression with synthetic HA messages; no NAS, HA account or real output.
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const card = await readFile(new URL('./feiniu-music-card.js',import.meta.url));
let imageRequests=0;
const server = createServer((req,res)=>{
  if(req.url.startsWith('/cover.svg')){imageRequests++;res.setHeader('Content-Type','image/svg+xml');res.setHeader('Cache-Control','private, max-age=30');res.end('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><path fill="#457" d="M0 0h64v64H0z"/></svg>');return;}
  res.setHeader('Content-Type',req.url==='/card.js'?'text/javascript; charset=utf-8':'text/html; charset=utf-8');
  res.end(req.url==='/card.js'?card:String.raw`<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;padding:10px;background:var(--primary-background-color,#f4f6f8);font-family:system-ui}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,350px),1fr));gap:16px}feiniu-music-card{min-width:0}</style></head><body><div class="grid"></div><script type="module">
  import '/card.js';
  window.calls=[];window.messages=[];window.linesDeferred=null;
  window.models={a:{revision:1,offset:0,total:3,current_id:'a-0',position:0,items:[{item_id:'a-0',track_id:'one',title:'After the rain',artist:'Synthetic ensemble',current:true},{item_id:'a-1',track_id:'two',title:'<img src=x onerror="window.injected=true">',artist:'Text, not HTML'},{item_id:'a-2',track_id:'three',title:'夜空中的回声',artist:'合成测试音乐'}],diagnostics:{phase:'playing',profile:{confirmation:'delivery',play_once:false,end_state:'idle',weak_end:false}}}};
  models.a.items.forEach((item,i)=>item.thumbnail='/cover.svg?i='+i);
  window.models.b=structuredClone(window.models.a);models.b.items.forEach(x=>x.item_id=x.item_id.replace('a','b'));models.b.current_id='b-0';
  window.hass={language:'zh-Hans',user:{is_admin:true},states:{},callService:async(domain,service,data)=>{calls.push({domain,service,data});},callWS:async(msg)=>{
    messages.push(msg);let key=msg.entity_id.endsWith('_b')?'b':'a';
    if(msg.type==='feiniu_music/queue'){if(window.queueDeferred)return new Promise(resolve=>{window.releaseQueue=resolve;});return structuredClone(models[key]);}
    if(msg.type==='feiniu_music/lyrics'){if(linesDeferred)return new Promise(resolve=>{window.releaseLyrics=resolve;});return {text:'A quiet room\nA familiar song',synced_lines:[{time_ms:0,text:'A quiet room'},{time_ms:4000,text:'A familiar song'}]};}
    if(msg.type==='media_player/browse_media')return {title:'Music library',children:[{title:'Evening playlist',thumbnail:'/cover.svg?browse=1',media_content_id:'media-source://feiniu_music/account/playlist/list',media_content_type:'playlist',can_expand:true,can_play:true}]};
    if(msg.type==='media_player/search_media')return {result:[{title:'Search single',media_content_id:'media-source://feiniu_music/account/track/one',media_content_type:'music',can_play:true}]};
    if(msg.type==='feiniu_music/edit_queue'){if(msg.revision!==models[key].revision)throw {code:'revision_conflict'};models[key].revision++;hass.states[msg.entity_id].attributes.queue_revision++;document.querySelectorAll('feiniu-music-card').forEach(c=>c.hass=hass);return {revision:models[key].revision};}
    return {saved:true};
  }};
  for(const key of ['a','b']){const id='media_player.feiniu_'+key;hass.states[id]={state:'playing',attributes:{feiniu_queue:true,friendly_name:key==='a'?'飞牛音乐 · 客厅':'飞牛音乐 · 书房',output_player:'media_player.output_'+key,queue_length:3,queue_revision:1,queue_item_id:key+'-0',playback_round:1,queue_active:true,session_phase:'playing',confirmation:'delivery',position_source:'native',supported_features:1048575,shuffle:false,repeat:'off',media_title:'After the rain',media_artist:'Synthetic ensemble',media_album_name:'Rooms / 合成音频',media_position:1,media_position_updated_at:new Date().toISOString(),media_duration:180,volume_level:.2}};hass.states['media_player.output_'+key]={attributes:{friendly_name:key==='a'?'客厅模拟输出':'书房模拟输出'}};const c=document.createElement('feiniu-music-card');c.setConfig({entity:id});c.hass=hass;document.querySelector('.grid').append(c);}
  </script></body></html>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await chromium.launch({headless:true, ...(process.env.CARD_BROWSER_CHANNEL ? {channel:process.env.CARD_BROWSER_CHANNEL} : {})});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});page.setDefaultTimeout(5000);page.on('console',m=>console.log('Browser:',m.type(),m.text()));page.on('requestfailed',r=>console.log('Request failed:',r.failure()?.errorText));
 await page.setViewportSize({width:390,height:844});await page.goto(`http://127.0.0.1:${server.address().port}`);
 const first=page.locator('feiniu-music-card').first(),second=page.locator('feiniu-music-card').nth(1);
 await first.locator('.row').first().waitFor().catch(async e=>{console.log(await page.evaluate(()=>({html:document.body.innerHTML.slice(0,600),messages:window.messages,states:[...document.querySelectorAll('feiniu-music-card')].map(c=>({connected:c._connected,queue:c._queue,text:c.shadowRoot?.textContent.slice(-500)}))})));throw e;});
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
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>window.injected),undefined);
 assert.equal(await first.locator('.row .name img').count(),0);
 assert.equal(await page.evaluate(()=>calls.length),0,'Rendering must not control outputs');
 await first.locator('#button-next').click();assert.equal(await page.evaluate(()=>calls.at(-1).data.entity_id),'media_player.feiniu_a');
 await second.locator('#button-stop').click();assert.equal(await page.evaluate(()=>calls.at(-1).data.entity_id),'media_player.feiniu_b');
 await first.getByRole('tab',{name:'歌词',exact:true}).click();await first.locator('#lyric-lines p').first().waitFor();
 await first.getByRole('tab',{name:'选择音乐',exact:true}).click();assert.equal(await first.getByRole('button',{name:'Evening playlist',exact:true}).count(),1);await first.getByRole('button',{name:'加入队列',exact:true}).click();
 assert.equal(await first.locator('#browse-list .row img').count(),1,'Browse uses the supplied HA thumbnail');
 assert.equal(await page.evaluate(()=>calls.at(-1).data.enqueue),'add');
 assert.equal(await page.evaluate(()=>calls.at(-1).data.media_content_id),'media-source://feiniu_music/account/playlist/list');
 await first.getByRole('tab',{name:'队列',exact:true}).click();
 await first.locator('.row').nth(1).getByRole('button',{name:'向后移动',exact:true}).click();
 assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/edit_queue').at(-1).item_id),'a-1');
 await first.getByRole('button',{name:'播放与歌词设置',exact:true}).click();await first.locator('#offset').fill('1.5');await first.getByRole('button',{name:'保存',exact:true}).click();
 assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='feiniu_music/preferences').at(-1).lyric_offset),1.5);
 // Stale lyric result must not replace the next track's lyrics.
 await page.evaluate(()=>{linesDeferred=true;const c=document.querySelector('feiniu-music-card');c._refreshLyrics();});
 await page.waitForFunction(()=>!!window.releaseLyrics);
 await page.evaluate(()=>{const c=document.querySelector('feiniu-music-card');const old=releaseLyrics;linesDeferred=null;hass.states['media_player.feiniu_a'].attributes.playback_round=2;c.hass=hass;old({text:'STALE_SENTINEL',synced_lines:[]});});
 await first.getByRole('tab',{name:'歌词',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('feiniu-music-card').shadowRoot.querySelector('#lyric-lines').textContent.includes('quiet'));
 assert.equal(await first.locator('#lyric-lines').getByText('STALE_SENTINEL').count(),0);
 // Hidden tabs stop animation and make no queue/lyrics calls.
 const hidden=await page.evaluate(async()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));const n=messages.length;const c=document.querySelector('feiniu-music-card');c._refresh();await new Promise(r=>setTimeout(r,200));return {count:messages.length-n,raf:c._raf};});
 assert.deepEqual(hidden,{count:0,raf:0});
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));});
 await mkdir('artifacts/card-preview',{recursive:true});
 for(const width of [360,390,430,1100]){
   await page.setViewportSize({width,height:960});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);
   await page.screenshot({path:`artifacts/card-preview/light-${width}.png`,fullPage:true});
 }
 await page.addStyleTag({content:':root{--primary-background-color:#101e25;--card-background-color:#1b2b35;--primary-text-color:#eef3f5;--secondary-text-color:#a5b6bf;--primary-color:#76cbd9;--secondary-background-color:#273c48;--divider-color:#3a4e5a;--text-primary-color:#102a33}'});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'artifacts/card-preview/dark-390.png',fullPage:true});
 assert.deepEqual(errors,[]);
 console.log('Browser checks passed: 2 independent cards, native actions, queue edits, safe text, stale lyrics, hidden page, 360/390/430/1100px, light/dark.');
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
