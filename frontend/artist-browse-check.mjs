// Exercise the shipped component and actual DOM against native-shaped browse replies.
import assert from 'node:assert/strict';

export async function checkArtistBrowse(browser, url) {
 const page=await browser.newPage({viewport:{width:1280,height:850},...(process.env.CARD_BROWSER_ENGINE==='webkit'?{isMobile:true,hasTouch:true}:{})});
 page.setDefaultTimeout(5000);
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 try {
  await page.goto(url);
  const card=page.locator('feiniu-music-card').first();
  await card.locator('.tile').first().waitFor();
  await page.evaluate(()=>{
   const base='media-source://feiniu_music/test/';
   const folder=(path,title)=>({title,media_class:'directory',media_content_id:base+path,media_content_type:'music',can_expand:true,can_play:false});
   const entry=(kind,id,title)=>({title,media_class:kind,media_content_type:kind==='track'?'music':kind,media_content_id:base+kind+'/'+id,can_expand:kind!=='track',can_play:kind==='track',thumbnail:'/cover.svg?i=1'});
   const artists=[['test-100','test 100'],['test-201','test 201'],['test-next','test next'],['test-labels','test labels']].map(([id,title])=>entry('artist',id,title));
   const roots=['track','album','artist','playlist'].map(kind=>folder(kind,kind[0].toUpperCase()+kind.slice(1)+'s'));
   window.artistReads=[];window.artistPending=[];window.holdArtistPath='';
   const reply=msg=>{
    const path=(msg.media_content_id||'').replace(base,'');
    if(!path)return {title:'test',children:roots};
    if(path==='artist')return {...roots[2],children:artists};
    if(path==='album'||path==='playlist')return {...folder(path,path),children:[]};
    const parts=path.split('/');
    if(parts[0]==='artist'&&parts.length===2){
     const artist=artists.find(x=>x.media_content_id===msg.media_content_id);
     const links=[folder(path+'/tracks','Tracks'),folder(path+'/albums','Albums')];
     // Titles and order are not an API discriminator. A page link is never a relation.
     if(parts[1]==='test-labels'){
      links[0].title='test songs';links[1].title='test releases';links.reverse();
      links.unshift({...folder(path+'/page/2/100','Tracks'),media_content_type:'feiniu_page'});
      links.unshift(folder(path+'/unrelated','Albums'));
     }
     return {...folder(path,artist.title),children:links};
    }
    if(parts[0]==='artist'&&['tracks','albums'].includes(parts[2])){
     const kind=parts[2]==='tracks'?'track':'album';
     const canonical=parts.slice(0,3).join('/'),number=parts[3]==='page'?Number(parts[4]):1;
     const total=parts[1]==='test-100'?100:201,offset=(number-1)*100;
     const rows=Array.from({length:Math.min(100,total-offset)},(_,i)=>{
      const position=offset+i;
      const title=position===100?'Tracks':position===101?'Albums':`test ${kind} ${position}`;
      const child=entry(kind,`test-${position}`,title);
      if(kind==='track')child.media_content_id=base+canonical+'/queue/'+position+'/test-'+position;
      return child;
     });
     for(const [n,title] of [[number-1,'Previous page'],[number+1,'Next page']]){
      if(n>=1&&(n-1)*100<total)rows.push({...folder(canonical+'/page/'+n+'/100',title),media_content_type:'feiniu_page'});
     }
     return {...folder(canonical,kind==='track'?'Tracks':'Albums'),children:rows,feiniu_paging:{offset,size:100,total,context_id:base+canonical}};
    }
    if(parts[0]==='album')return {...folder(path,parts[1]==='test-100'?'Tracks':'Albums'),children:[entry('track','test-album-song','Albums')]};
    throw new Error('Unexpected synthetic browse path');
   };
   const original=hass.callWS;
   hass.callWS=msg=>{
    if(msg.type!=='media_player/browse_media')return original(msg);
    artistReads.push(msg);
    if(window.holdArtistPath&&msg.media_content_id===base+holdArtistPath){
     return new Promise(resolve=>artistPending.push(()=>resolve(reply(msg))));
    }
    return Promise.resolve(reply(msg));
   };
   window.artistCard=document.querySelector('feiniu-music-card');
   artistCard.setConfig({entity:'media_player.feiniu_a',display_mode:'full'});
  });
  const heading=card.locator('#browse-heading h1');
  const relations=card.locator('#relations');
  const list=card.locator('#browse-list');
  const next=()=>list.getByRole('button',{name:'下一页',exact:true});
  const previous=()=>list.getByRole('button',{name:'上一页',exact:true});
  async function openArtist(name){
   await card.getByRole('button',{name:'歌手',exact:true}).click();
   await list.getByRole('button',{name,exact:true}).click();
   await list.locator('.row').first().waitFor();
  }
  async function assertArtist(name,tab='歌曲',labels=['歌曲','专辑']){
   assert.deepEqual({title:await heading.textContent(),tabsVisible:await relations.isVisible(),tabs:await relations.locator('button').allTextContents(),active:await relations.locator('button.active').allTextContents(),artwork:await card.locator('#browse-heading.hero.artist .hero-cover').count()},
    {title:name,tabsVisible:true,tabs:labels,active:[tab],artwork:1},'Artist title, detail and explicit relation tabs survive navigation');
  }
  await openArtist('test 100');
  assert.equal(await list.locator('.row').count(),100);
  assert.equal(await list.locator('.pager').count(),0);
  await assertArtist('test 100');
  console.log('Artist control passed: 100 tracks, no pagination.');

  await openArtist('test 201');
  assert.equal(await list.locator('.row').count(),100);
  await assertArtist('test 201'); // ada2e06 loses its artist title/tabs here.
  assert.equal(await next().count(),1);
  await next().click();
  assert.equal(await list.locator('.number').first().textContent(),'101');
  assert.deepEqual(await list.locator('.row-title').allTextContents().then(t=>t.slice(0,2)),['Tracks','Albums']);
  await assertArtist('test 201');
  await list.locator('.number').first().click();
  assert.equal(await page.evaluate(()=>calls.at(-1).data.media_content_id),'media-source://feiniu_music/test/artist/test-201/tracks/queue/100/test-100');
  await card.locator('#browse-heading').getByRole('button',{name:'播放全部',exact:true}).click();
  assert.equal(await page.evaluate(()=>calls.at(-1).data.media_content_id),'media-source://feiniu_music/test/artist/test-201/tracks');
  await next().click();
  assert.equal(await list.locator('.row').count(),1);
  assert.equal(await list.locator('.number').first().textContent(),'201');
  assert.equal(await next().count(),0);
  await assertArtist('test 201');
  await previous().click();await assertArtist('test 201');
  assert.equal(await list.locator('.number').first().textContent(),'101');
  await previous().click();await assertArtist('test 201');
  assert.equal(await list.locator('.number').first().textContent(),'1');
  assert.equal(await previous().count(),0);

  await relations.getByRole('button',{name:'专辑',exact:true}).click();
  await assertArtist('test 201','专辑');
  assert.equal(await list.locator('.tile').count(),100);
  await next().click();await assertArtist('test 201','专辑');
  assert.deepEqual(await list.locator('.tile-title').allTextContents().then(t=>t.slice(0,2)),['Tracks','Albums']);
  // These album titles must open album contents, not rewrite artist context.
  for(const title of ['Tracks','Albums']){
   await list.getByRole('button',{name:title,exact:true}).click();
   assert.equal(await heading.textContent(),title);
   assert.equal(await relations.isVisible(),false);
   await card.locator('#browse-back button').click();
   await assertArtist('test 201','专辑');
   assert.equal(await list.locator('.tile-title').first().textContent(),'Tracks');
  }
  await next().click();await assertArtist('test 201','专辑');
  assert.equal(await list.locator('.tile').count(),1);
  assert.equal(await next().count(),0);
  await previous().click();await assertArtist('test 201','专辑');
  await previous().click();await assertArtist('test 201','专辑');
  await relations.getByRole('button',{name:'歌曲',exact:true}).click();
  await assertArtist('test 201');
  await card.locator('#browse-back button').click();
  assert.equal(await list.locator('.tile').count(),4,'Back leaves the artist without duplicate page/tab history');
  assert.equal(await relations.isVisible(),false);

  await openArtist('test labels');
  await assertArtist('test labels','test songs',['test songs','test releases']);
  await relations.getByRole('button',{name:'test releases',exact:true}).click();
  await assertArtist('test labels','test releases',['test songs','test releases']);
  await page.evaluate(()=>artistCard._browse({title:'test next',media_class:'artist',media_content_type:'artist',media_content_id:'media-source://feiniu_music/test/artist/test-next',can_expand:true}));
  await assertArtist('test next');
  await card.locator('#browse-back button').click();
  await assertArtist('test labels','test releases',['test songs','test releases']);
  // Invalidate both a late detail response and a late relationship response.
  for(const path of ['artist/test-201','artist/test-201/tracks']){
   await page.evaluate(path=>{window.holdArtistPath=path;artistCard._browse({title:'test 201',media_class:'artist',media_content_type:'artist',media_content_id:'media-source://feiniu_music/test/artist/test-201',can_expand:true});},path);
   await page.waitForFunction(()=>artistPending.length===1);
   await page.evaluate(()=>{window.holdArtistPath='';return artistCard._browse({title:'test next',media_class:'artist',media_content_type:'artist',media_content_id:'media-source://feiniu_music/test/artist/test-next',can_expand:true});});
   await assertArtist('test next');
   await page.evaluate(()=>artistPending.shift()());
   await assertArtist('test next');
   await next().click();await assertArtist('test next');
   assert.equal(await list.locator('.number').first().textContent(),'101');
  }
  assert.deepEqual(errors,[]);
  console.log('Artist browser checks passed: 100/201 tracks, second/last/previous pages, album pages, title collisions, localized relation links, back navigation, stale artist replies, global positions and play-all URIs.');
 } finally {await page.close();}
}
