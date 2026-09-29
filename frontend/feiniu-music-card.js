// FeiNiu queue card: HA owns playback, this component only renders and sends user actions.
import {CARD_CSS} from './card-styles.js';
import {CARD_ICONS} from './card-icons.js';
import {CARD_FONT} from './card-font.js';
import {CARD_BRAND} from './card-brand.js';
import {COMPACT_CSS} from './card-compact.js';
import './card-editor.js';
export const VERSION = '0.3.0-plain-lyrics';
let fontReady;
function loadCardFont(){
  if(!globalThis.FontFace||fontReady)return;
  const font=new FontFace('FeiNiu Card Montserrat',`url(${CARD_FONT})`,{weight:'400 700',display:'swap'});
  fontReady=font.load().then(f=>document.fonts.add(f)).catch(()=>{});
}
export function timeLabel(value) {
  if (!Number.isFinite(value) || value < 0) return '—';
  const seconds = Math.floor(value);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
export function lyricIndex(lines, seconds, offset = 0) {
  let low = 0, high = lines.length;
  const target = (seconds + offset) * 1000;
  while (low < high) { const mid = (low + high) >>> 1; if (lines[mid].time_ms <= target) low = mid + 1; else high = mid; }
  return low - 1;
}
export function lyricSeekPosition(milliseconds, offset, duration) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0 || !Number.isFinite(offset) || !Number.isFinite(duration) || duration <= 0) return null;
  // Display advances by offset; seeking to that displayed line applies the inverse.
  return Math.max(0, Math.min(duration, milliseconds / 1000 - offset));
}
export function positionAt(attributes, state, now) {
  const value = attributes.media_position, timestamp = Date.parse(attributes.media_position_updated_at);
  if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isFinite(timestamp)) return null;
  const age = state === 'playing' ? Math.max(0, (now - timestamp) / 1000) : 0;
  return Math.max(0, Math.min(value + age, attributes.media_duration || Infinity));
}
export function safeImage(value) {
  if (typeof value !== 'string') return null;
  if (value.startsWith('/') && !value.startsWith('//')) return value;
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}
const PLAYBACK_MODES = [
  {icon:'sequence',label:'shuffleOff',shuffle:false,repeat:'off'},
  {icon:'shuffle',label:'shuffleOn',shuffle:true,repeat:'off'},
  {icon:'repeat',label:'repeatAll',shuffle:false,repeat:'all'},
  {icon:'repeat-one',label:'repeatOne',shuffle:false,repeat:'one'},
];
function playbackMode(a){return a.repeat==='one'?3:a.shuffle?1:a.repeat==='all'?2:0;}
const words = {
  en: { queue: 'Queue', lyrics: 'Lyrics', browse: 'Choose music', empty: 'Choose an album, playlist or track to begin.',
    next: 'Next', previous: 'Previous', play: 'Play / retry', pause: 'Pause', stop: 'Stop', shuffle: 'Shuffle', repeat: 'Repeat',
    volume: 'Volume', seek: 'Playback position', clear: 'Clear queue', more: 'More', back: 'Back', pagePrevious:'Previous page', pageNext:'Next page',
    remove: 'Remove', up: 'Move earlier', down: 'Move later', jump: 'Play this item', add: 'Add to queue', playnext: 'Play next',
    search: 'Search music', searchGo: 'Search', loading: 'Loading…', compactLoading:'Loading', noLyrics: 'No lyrics for this track.', lyricError: 'Lyrics unavailable. Playback is unaffected.',
    settings: 'Playback & lyrics', offset: 'Lyrics offset (seconds)', save: 'Save', saved: 'Saved', close: 'Close',
    confirmation: 'Start confirmation', delivery: 'Audio delivery or fresh device progress', reported: 'Trust the output’s playing report',
    playOnce: 'Send one extra Play after loading', end: 'Output reports completion as', weak: 'Allow completion without reliable progress',
    warning: 'PAUSED/OFF or weak completion can mistake a device-side pause/stop for completion. Keep defaults unless you have tested this output.',
    diagnostic: 'Playback diagnostics', error: 'The operation failed. Refresh or retry.', conflict: 'The queue changed. It has been refreshed.',
    PermissionDeniedError:'This music account can no longer access the track.', NotFoundError:'The track is unavailable.', AuthenticationError:'Update this music account’s password in integration settings.', NetworkError:'The music service is temporarily unreachable.', ProtocolError:'The music service returned an unexpected response.',
    offline: 'Output offline. The queue is kept.', idle: 'Ready', restored: 'Queue restored · press Play to continue',
    playing: 'Playing', paused: 'Paused', buffering: 'Buffering', detached: 'Another source took control · press Play to resume',
    failed: 'Playback stopped · retry or skip this item', ended: 'Queue finished', estimated: 'Estimated progress',
    start_unconfirmed: 'Playback has not been confirmed · retry is available', reported_without_delivery: 'Output reports playing; waiting for audio or device progress',
    stream_failed: 'Audio delivery failed · retry or update the music login', footer: 'Each output has its own queue. Changes here do not edit the NAS playlist.',
    source: 'Output', unknown: 'No track selected', browseAll: 'Play this list', count: 'items', emptyQueue: 'Queue empty',
  },
  zh: { queue: '队列', lyrics: '歌词', browse: '选择音乐', empty: '选择专辑、歌单或歌曲开始播放。',
    next: '下一首', previous: '上一首', play: '播放／重试', pause: '暂停', stop: '停止', shuffle: '随机', repeat: '循环',
    volume: '音量', seek: '播放进度', clear: '清空队列', more: '更多', back: '返回', pagePrevious:'上一页', pageNext:'下一页',
    remove: '移除', up: '向前移动', down: '向后移动', jump: '播放这一项', add: '加入队列', playnext: '下一首播放',
    search: '搜索音乐', searchGo: '搜索', loading: '正在加载…', compactLoading:'加载中', noLyrics: '这首歌暂无歌词。', lyricError: '歌词暂时不可用，不影响播放。',
    settings: '播放与歌词设置', offset: '歌词偏移（秒）', save: '保存', saved: '已保存', close: '关闭',
    confirmation: '起播确认', delivery: '收到音频或新的设备进度', reported: '相信输出报告的播放状态',
    playOnce: '加载后补发一次播放动作', end: '设备结束时报告的状态', weak: '允许无可靠进度时按结束状态续播',
    warning: '将暂停／关机或弱反馈作为结束，可能误判音箱上的暂停、停止操作。未验证设备时请保留默认设置。',
    diagnostic: '播放诊断', error: '操作未完成，请刷新或重试。', conflict: '队列已经变化，已为你刷新。',
    PermissionDeniedError:'当前音乐账号已无权访问这首歌。', NotFoundError:'歌曲文件不可用。', AuthenticationError:'请在集成设置中更新音乐账号密码。', NetworkError:'暂时无法连接音乐服务，可稍后重试。', ProtocolError:'音乐服务返回了非预期响应。',
    offline: '输出离线，队列已保留。', idle: '准备就绪', restored: '队列已恢复 · 点击播放继续',
    playing: '正在播放', paused: '已暂停', buffering: '正在缓冲', detached: '其他来源已接管 · 点击播放可继续',
    failed: '播放已停止 · 可重试或跳过本项', ended: '队列播放完毕', estimated: '估算进度',
    start_unconfirmed: '尚未确认起播 · 可以重试', reported_without_delivery: '输出报告播放中，等待音频或设备进度',
    stream_failed: '音频传输失败 · 请重试或更新音乐账号登录', footer: '每个输出有独立队列；这里的编辑不会修改 NAS 歌单。',
    source: '输出', unknown: '尚未选择歌曲', browseAll: '播放整个列表', count: '项', emptyQueue: '队列为空',
  },
};
Object.assign(words.en, {browse:'Library', lyrics:'Now playing', queue:'Play queue',
  track:'Track', album:'Album', artist:'Artist', playlist:'Playlist', tracks:'Tracks', albums:'Albums', artists:'Artists', playlists:'Playlists',
  library:'Your music', results:'Search results', noResults:'No music found.', browseAll:'Play all',
  trackInfo:'Track details', detailHint:'Play this track to view its lyrics.', lyricLabel:'LYRICS',
  name:'Title', actions:'Actions', retry:'Retry', queueHint:'Your next songs, in order.',
  shuffleOn:'Shuffle play', shuffleOff:'Play in order', closeVolume:'Close volume',
  fullscreen:'Full screen', exitFullscreen:'Exit full screen', fullscreenError:'Full screen could not open. Try opening Home Assistant in a browser.',
  lyricEarlier:'Lyrics earlier by 0.5 s', lyricLater:'Lyrics later by 0.5 s', lyricCentre:'Centre this lyric without seeking', lyricSeek:'Play from', lyricSeekUnavailable:'This output cannot seek the current track', lyricReset:'Reset lyrics offset', lyricDefault:'Lyrics timing reset',
  plainLyrics:'Untimed lyrics · Scroll to read; line seeking is unavailable',
  compactDetached:'External playback · Play to resume', compactFailed:'Playback failed · Play to retry', compactOffline:'Output offline', compactEmpty:'Choose music', compactWaiting:'Waiting for position', lyricWaiting:'Waiting for playback position',
  repeatOff:'Repeat off', repeatOne:'Repeat one', repeatAll:'Repeat all'});
Object.assign(words.zh, {browse:'音乐库', lyrics:'正在播放', queue:'播放队列',
  track:'歌曲', album:'专辑', artist:'歌手', playlist:'歌单', tracks:'歌曲', albums:'专辑', artists:'歌手', playlists:'歌单',
  library:'我的音乐', results:'搜索结果', noResults:'没有找到音乐。', browseAll:'播放全部',
  trackInfo:'歌曲详情', detailHint:'播放这首歌后，可在正在播放页查看歌词。', lyricLabel:'歌词',
  name:'歌曲', actions:'操作', retry:'重试', queueHint:'接下来播放的歌曲，按顺序排列。',
  shuffleOn:'随机播放', shuffleOff:'顺序播放', closeVolume:'关闭音量',
  fullscreen:'全屏', exitFullscreen:'退出全屏', fullscreenError:'无法进入全屏，可尝试在浏览器中打开 Home Assistant。',
  lyricEarlier:'歌词提前 0.5 秒', lyricLater:'歌词延后 0.5 秒', lyricCentre:'居中此句歌词，不跳转播放', lyricSeek:'从此处播放', lyricSeekUnavailable:'当前输出无法定位这首歌', lyricReset:'重置歌词偏移', lyricDefault:'歌词偏移已恢复默认',
  plainLyrics:'纯文本歌词 · 可手动滚动，无时间轴，不能按句跳转',
  compactDetached:'其他来源播放 · 点播放继续', compactFailed:'播放失败 · 点播放重试', compactOffline:'设备离线', compactEmpty:'等待选曲', compactWaiting:'等待播放进度', lyricWaiting:'等待播放进度',
  repeatOff:'循环关闭', repeatOne:'单曲循环', repeatAll:'列表循环'});
// HA supplies the media class; category folders can be recognized by their media-source path.
export function mediaKind(item) {
  if (['track','album','artist','playlist'].includes(item?.media_class)) return item.media_class;
  const parts = (item?.media_content_id || '').split('/');
  if (parts.includes('queue')) return 'track';
  return ['track','album','artist','playlist'].find(kind => parts.includes(kind)) || 'directory';
}
const icons = {
  mode:'sequence', previous:'previous', play:'play', pause:'pause', next:'next', stop:'stop', shuffle:'shuffle', repeat:'repeat',
  fullscreen:'fullscreen', exitFullscreen:'fullscreen-exit', browse:'library', settings:'settings', remove:'close', close:'close', up:'arrow-up', down:'arrow-down',
  add:'playlist-add', playnext:'play-next', back:'arrow-left', pagePrevious:'arrow-left', pageNext:'arrow-right', home:'home', more:'more', minimize:'arrow-down',
  queue:'queue', lyrics:'now-playing', album:'disc', artist:'artist', playlist:'playlist', track:'music-note',
  volume:'volume', search:'search', clear:'trash', save:'check', retry:'refresh', jump:'play', trackInfo:'music-note',
  lyricEarlier:'lyric-earlier', lyricLater:'lyric-later',
};
const Base = globalThis.HTMLElement || class {};
class FeiNiuIcon extends Base {
  static get observedAttributes(){return ['icon'];}
  connectedCallback(){this.paint();}
  attributeChangedCallback(){this.paint();}
  paint(){
    if(!this.shadowRoot)this.attachShadow({mode:'open'});
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
    svg.style.cssText='display:block;width:var(--mdc-icon-size,23px);height:var(--mdc-icon-size,23px);margin:auto';
    const name=(this.getAttribute('icon')||'').replace('mdi:','');
    svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
    svg.setAttribute('stroke-width','1.8');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');
    for(const attrs of CARD_ICONS[name] || CARD_ICONS['music-note']){
      const path=document.createElementNS(svg.namespaceURI,'path');
      for(const [key,value] of Object.entries(attrs))path.setAttribute(key,value);
      svg.append(path);
    }
    this.shadowRoot.replaceChildren(svg);
  }
}
if(globalThis.customElements&&!customElements.get('feiniu-icon'))customElements.define('feiniu-icon',FeiNiuIcon);
export class FeiNiuMusicCard extends Base {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this._tab = 'browse'; this._offset = 0; this._queue = null; this._queueEpoch = 0; this._lyricEpoch = 0;
    this._connected = false; this._busy = false; this._lyrics = []; this._lyricText = ''; this._lastLine = -1;
    this._roots=[]; this._browseResult=null; this._playlistRows=null; this._browseStack = []; this._browseEpoch = 0; this._queuePending = false; this._queueAgain = false;
    this._volumeOutside=e=>{const path=e.composedPath();if(!path.includes(this.$('volume-control')))this._closeVolume();if(this._queueOpen&&!path.includes(this.$('queue-view'))&&!path.includes(this.$('now-queue')))this._closeQueue();};
    this._fullscreenChanged=()=>this._syncFullscreen();
    this._visibility = () => { if (document.hidden) {this._stopAnimation();this._stopViewTransition();this._clearLyricInteraction();} else { this._refresh(); this._animate(); } };
  }
  setConfig(config) {
    if (!config.entity || !config.entity.startsWith('media_player.')) throw new Error('Choose a FeiNiu media_player entity');
    if(config.display_mode&&!['compact','full'].includes(config.display_mode))throw new Error('display_mode must be compact or full');
    if(config.compact_view&&!['simple','lyrics','auto'].includes(config.compact_view))throw new Error('compact_view must be simple, lyrics or auto');
    if(config.compact_background&&!['default','artwork'].includes(config.compact_background))throw new Error('compact_background must be default or artwork');
    if(config.compact_mask&&!['soft','glass'].includes(config.compact_mask))throw new Error('compact_mask must be soft or glass');
    if(config.entity!==this._config?.entity){this._lyricResultKey='';this._lyrics=[];this._lyricText='';}
    this._finishExpanded(false);
    this._queueEpoch++; this._lyricEpoch++; this._lyricPendingKey='';this._browseEpoch++; this._queueAgain=this._queuePending;
    this._stopViewTransition();this._clearLyricInteraction();this._offsetEdit=null;
    this._roots=[]; this._browseResult=null; this._browseItem=null; this._artistContext=null; this._playlistRows=null; this._browseStarted=false; this._browseStack=[]; this._offset=0;
    this._config = {...config}; this._key = ''; this._lyricKey = ''; this._queue = null;
    if (this._connected) { this._build(); this._render(); }
  }
  getCardSize() { return this._config?.display_mode==='compact'?(this._compactRich?8:5):12; }
  getGridOptions() { return this._config?.display_mode==='compact'?{columns:12,min_columns:9,rows:this._compactRich?8:5,min_rows:this._compactRich?8:5}:{columns:12,rows:12,min_columns:6,min_rows:8}; }
  static getStubConfig(hass) { return {entity:Object.keys(hass.states).find(id=>id.startsWith('media_player.')&&hass.states[id].attributes.feiniu_queue),display_mode:'compact',compact_view:'auto',compact_background:'artwork',compact_mask:'soft',theme:'dark'}; }
  static getConfigElement(){return document.createElement('feiniu-music-card-editor');}
  set hass(value) {
    this._hass = value;
    if (!this._connected || !this._config) return;
    this._render();
  }
  connectedCallback() {
    this._connected = true;document.addEventListener('fullscreenchange',this._fullscreenChanged); document.addEventListener('visibilitychange', this._visibility);document.addEventListener('pointerdown',this._volumeOutside);
    // HA masonry can detach/reinsert a card while its first request is pending.
    // The old epoch must be discarded, then replaced even if state keys did not change.
    this._key = ''; this._lyricKey = ''; this._queueAgain = this._queuePending;
    if (this._config) { this._build(); this._render(); }
  }
  disconnectedCallback() {
    this._connected = false; this._browseStarted=false; this._queueEpoch++; this._lyricEpoch++;this._lyricPendingKey=''; this._browseEpoch++;
    this._finishExpanded(false);
    this._stopAnimation();this._stopViewTransition();this._clearLyricInteraction();this._lyricObserver?.disconnect();document.removeEventListener('fullscreenchange',this._fullscreenChanged); document.removeEventListener('visibilitychange', this._visibility);document.removeEventListener('pointerdown',this._volumeOutside);
  }
  get _state() { return this._hass?.states[this._config?.entity]; }
  get _compactHome(){return this._config?.display_mode==='compact'&&!this._expanded;}
  get _compactRich(){return this._config?.compact_view==='lyrics'||(this._config?.compact_view==='auto'&&!!(this._lyrics?.length||this._lyricText?.trim()));}
  get _lyricsVisible(){return this._compactHome?!!this._compactShowLyrics:this._tab==='lyrics';}
  get _attrs() { return this._state?.attributes || {}; }
  t(key) { return (words[this._hass?.language?.startsWith('zh') ? 'zh' : 'en'][key] || words.en[key] || key); }
  $(id) { return this.shadowRoot.getElementById(id); }
  _text(id, value) { this.$(id).textContent = value || ''; }
  _button(key, action, label) {
    const b = document.createElement('button'); b.type = 'button'; b.title = label || this.t(key); b.setAttribute('aria-label', b.title);
    if (icons[key]) { const i = document.createElement('feiniu-icon'); i.setAttribute('icon', `mdi:${icons[key]}`); b.append(i); if (label) b.append(document.createTextNode(label)); }
    else b.textContent = label || this.t(key);
    b.addEventListener('click', action); return b;
  }
  _build() {
    this._finishExpanded(false);
    this._stopViewTransition();this._lyricObserver?.disconnect();
    loadCardFont();this._queueRows=new Map();this._lyricsPaintKey='';this._compactArtURL='';this._language=this._hass?.language||'en';
    // Constant markup only. Music titles, lyrics and all service data use textContent.
    this.shadowRoot.innerHTML=`<style>${CARD_CSS}${COMPACT_CSS}</style><ha-card class="shell"><img id="ambient" class="ambient" hidden alt=""><div id="compact-background" class="compact-background" aria-hidden="true"><img alt=""><img alt=""></div><span id="now-back" hidden></span>
      <header class="compact-heading"><div class="compact-labels"><strong id="compact-title" class="truncate"></strong><small id="compact-output" class="truncate"></small></div><span id="compact-open"></span></header>
      <div class="brand"><span class="brand-mark"><img src="${CARD_BRAND}" alt=""></span><span id="heading"></span></div>
      <header class="topbar"><form class="search"><feiniu-icon icon="mdi:search"></feiniu-icon><input id="search" type="search"><button id="search-go" type="submit"><feiniu-icon icon="mdi:arrow-left" style="transform:rotate(180deg)"></feiniu-icon></button></form><div class="top-tools"><span id="output" class="output-badge truncate"></span><span id="settings-button"></span></div></header>
      <aside class="sidebar"><div class="tabs" role="tablist"></div><nav id="categories" class="categories"></nav><div id="playlist-caption" class="nav-caption"></div><nav id="playlist-nav" class="playlist-nav"></nav><div id="sidebar-note" class="sidebar-bottom"></div></aside>
      <main id="main" class="main"><section id="browser"><div class="view-top"><span id="browse-back"></span><div id="breadcrumbs" class="breadcrumbs"></div></div><nav id="mobile-categories" class="mobile-categories"></nav><div id="browse-heading"></div><div id="relations" class="relation-tabs" hidden></div><div id="browse-all"></div><div id="browse-list"></div></section>
        <section id="queue-view" hidden><div class="queue-heading"><div><h1 id="queue-title"></h1><p id="queue-hint" class="muted"></p></div><span id="queue-clear"></span><span id="queue-close" hidden></span></div><div id="content"></div></section>
        <section id="now-view" class="now-view" hidden><div class="now-info"><div class="now-art"><feiniu-icon icon="mdi:music-note"></feiniu-icon><img id="art" hidden alt=""></div><h2 id="title"></h2><div class="now-meta"><span id="artist"></span><span id="album"></span></div></div><div class="lyric-panel"><div id="lyric-label" class="lyric-label"></div><div id="lyric-lines" tabindex="0"></div><div id="lyric-tools" hidden></div><div id="lyric-notice" role="status" aria-live="polite"></div></div></section>
      </main>
      <footer class="dock"><button id="mini-open" class="mini-info"><span class="mini-cover"><feiniu-icon icon="mdi:music-note"></feiniu-icon><img id="mini-art" hidden alt=""></span><span class="mini-text"><strong id="mini-title"></strong><small id="mini-artist"></small></span></button><div class="transport"><div id="controls"></div><div class="progress"><span id="elapsed">—</span><input id="seek" type="range" min="0" max="100" step="1"><span id="duration">—</span></div></div><div id="dock-tools" class="dock-tools"></div><div id="status" role="status" aria-live="polite"></div></footer>
      <div id="error" role="alert"></div>
      <div id="preferences" class="overlay" hidden><section class="dialog" role="dialog" aria-modal="true" aria-labelledby="settings-heading"><div class="dialog-header"><h2 id="settings-heading"></h2><span id="settings-close"></span></div><div id="preference-fields"></div><span id="save-preferences"></span><p id="warning" class="muted"></p><details><summary id="diagnostic-label"></summary><pre id="diagnostics" class="diagnostics"></pre></details><p id="footer" class="muted"></p></section></div>
      <div id="track-sheet" class="overlay" hidden><section class="dialog" role="dialog" aria-modal="true" aria-labelledby="track-detail-title"><div class="dialog-header"><h2 id="track-heading"></h2><span id="track-close"></span></div><div id="track-detail-art" class="track-detail-art"></div><h3 id="track-detail-title" class="track-detail-title"></h3><p id="track-detail-sub" class="track-detail-sub"></p><div id="track-actions" class="track-actions"></div><p id="track-hint" class="muted"></p></section></div>
    </ha-card><dialog id="expanded-dialog" class="expanded-dialog"><div id="expanded-frame" class="expanded-frame"><header class="expanded-heading"><span id="expanded-title"></span><span id="expanded-close"></span></header></div></dialog>`;
    const stage=document.createElement('section');stage.id='compact-stage';stage.hidden=true;
    this.shadowRoot.querySelector('.dock').append(stage);this._lyricPanel=this.shadowRoot.querySelector('.lyric-panel');
    const status=document.createElement('span');status.id='compact-status';status.hidden=true;status.setAttribute('role','status');
    this.shadowRoot.querySelector('.progress').append(status);
    const height=Number(this._config.height);if(Number.isFinite(height)&&height>0)this.shadowRoot.querySelector('.shell').style.setProperty('--fn-height',`${Math.max(600,Math.min(1200,height))}px`);
    this.shadowRoot.querySelector('.sidebar').prepend(this.shadowRoot.querySelector('.brand'));
    this.shadowRoot.querySelector('.topbar').prepend(this.$('browse-back'));
    this.$('now-back').append(this._button('minimize',()=>this._showTab('browse'),this.t('back')));
    const fullscreen=this._button('fullscreen',()=>this._toggleFullscreen());fullscreen.id='now-fullscreen';this.shadowRoot.querySelector('.shell').append(fullscreen);
    this.$('settings-button').append(this._button('settings',()=>this._preferences()));
    const expand=this._button('fullscreen',()=>this._showTab('browse'));expand.title=this.t('browse');expand.setAttribute('aria-label',expand.title);this.$('compact-open').append(expand);
    this.$('expanded-close').append(this._button('close',()=>this._closeExpanded()));
    this.$('expanded-dialog').setAttribute('aria-label',this.t('browse'));
    this.$('expanded-dialog').addEventListener('cancel',e=>{e.preventDefault();this._closeExpanded();});
    this.$('expanded-dialog').addEventListener('close',()=>{if(!this.$('expanded-dialog').open)this._finishExpanded();});
    for(const [key,step] of [['lyricEarlier',.5],['lyricLater',-.5]]){const b=this._button(key,()=>this._adjustLyricOffset(step));b.id=key;this.$('lyric-tools').append(b);}
    const reset=this._button('lyricReset',()=>this._adjustLyricOffset(0));reset.id='lyric-offset-value';this.$('lyric-tools').append(reset);
    const lyricBox=this.$('lyric-lines');lyricBox.setAttribute('role','region');lyricBox.setAttribute('aria-label',this.t('lyricLabel'));
    lyricBox.addEventListener('wheel',()=>this._holdLyrics(),{passive:true});
    lyricBox.addEventListener('touchstart',()=>this._holdLyrics(),{passive:true});
    lyricBox.addEventListener('scroll',()=>{if(this._lyricsManual)this._holdLyrics();this._queueLyricPaint();},{passive:true});
    lyricBox.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(e.key))this._holdLyrics();});
    lyricBox.addEventListener('focusin',e=>{if(e.target.closest('.lyric-row'))this._holdLyrics();});
    this._lyricObserver=new ResizeObserver(()=>this._queueLyricPaint(true));this._lyricObserver.observe(lyricBox.parentElement);
    this._buttons={};
    for(const key of ['mode','previous','play','next','stop']){
      const b=this._button(key,()=>this._transport(key));if(key==='mode')b.dataset.mode='playback';b.id=`button-${key}`;if(key==='play')b.className='main';this.$('controls').append(b);this._buttons[key]=b;
    }
    const stop=this._button('stop',()=>this._transport('stop'));stop.className='dock-stop';
    const mode=this._button('mode',()=>this._transport('mode'));mode.dataset.mode='playback';this.$('dock-tools').append(mode);
    const queueButton=this._button('queue',()=>this._showTab('queue'));queueButton.className='queue-toggle';
    const volumeControl=document.createElement('div');volumeControl.id='volume-control';
    const volumeButton=this._button('volume',()=>this._toggleVolume());volumeButton.id='volume-toggle';volumeButton.setAttribute('aria-expanded','false');volumeButton.setAttribute('aria-controls','volume-pop');volumeControl.append(volumeButton);
    const pop=document.createElement('div');pop.id='volume-pop';pop.hidden=true;pop.setAttribute('role','group');pop.setAttribute('aria-label',this.t('volume'));
    // Static controls only; labels and values are assigned separately.
    pop.innerHTML='<div class="volume-heading"><label id="volume-label" for="volume"></label><output id="volume-value" for="volume"></output><span id="volume-close"></span></div><input id="volume" type="range" min="0" max="1" step="0.01">';
    volumeControl.append(pop);this.$('dock-tools').append(stop,queueButton,volumeControl);
    const cornerQueue=this._button('queue',()=>{this._queueOpen=!this._queueOpen;this._renderContent();if(this._queueOpen)this.$('queue-close').firstChild.focus();});cornerQueue.id='now-queue';cornerQueue.hidden=true;this.shadowRoot.querySelector('.shell').append(cornerQueue);
    this.$('queue-close').append(this._button('close',()=>this._closeQueue(true)));
    this.$('queue-view').onkeydown=e=>{if(e.key==='Escape'&&this._queueOpen){e.stopPropagation();this._closeQueue(true);}};
    this.$('volume-close').append(this._button('close',()=>this._closeVolume(true)));this.$('volume-close').firstChild.setAttribute('aria-label',this.t('closeVolume'));this.$('volume-close').firstChild.title=this.t('closeVolume');
    volumeControl.onkeydown=e=>{if(e.key==='Escape'&&!this.$('volume-pop').hidden){e.stopPropagation();this._closeVolume(true);}};
    for(const key of ['browse','queue']){const b=this._button(key==='browse'?'home':key,()=>this._showTab(key),this.t(key));b.setAttribute('role','tab');b.dataset.tab=key;this.shadowRoot.querySelector('.tabs').append(b);}
    this.$('mini-open').onclick=()=>this._showTab('lyrics');this.$('mini-open').setAttribute('aria-label',this.t('lyrics'));
    this.$('seek').setAttribute('aria-label',this.t('seek'));
    this.$('seek').oninput=()=>{this._dragging=true;this._text('elapsed',timeLabel(Number(this.$('seek').value)));};
    this.$('seek').onchange=()=>{this._dragging=false;this._service('media_seek',{seek_position:Number(this.$('seek').value)});};
    this.$('volume').setAttribute('aria-label',this.t('volume'));this._text('volume-label',this.t('volume'));
    this.$('volume').oninput=()=>this._text('volume-value',`${Math.round(Number(this.$('volume').value)*100)}%`);
    this.$('volume').onchange=()=>this._service('volume_set',{volume_level:Number(this.$('volume').value)});
    for(const id of ['art','mini-art'])this.$(id).onerror=()=>{this.$(id).hidden=true;this.$(id).previousElementSibling.hidden=false;};
    this.$('browse-back').append(this._button('back',()=>this._back()));
    this.$('search').placeholder=this.t('search');this.$('search').setAttribute('aria-label',this.t('search'));this.$('search-go').setAttribute('aria-label',this.t('searchGo'));
    this.shadowRoot.querySelector('form').onsubmit=e=>{e.preventDefault();const query=this.$('search').value.trim();if(query){this._showTab('browse',false);this._browse(null,true,query);}};
    for(const [id,key] of [['queue-title','queue'],['lyric-label','lyricLabel'],['playlist-caption','playlists'],['footer','footer'],['warning','warning'],['diagnostic-label','diagnostic'],['settings-heading','settings'],['track-heading','trackInfo'],['track-hint','detailHint']])this._text(id,this.t(key));
    this.$('queue-clear').append(this._button('stop',()=>this._transport('stop'),this.t('stop')));
    this.$('queue-clear').append(this._button('clear',()=>this._edit('clear'),this.t('clear')));
    for(const [id,close] of [['preferences','settings-close'],['track-sheet','track-close']]){
      this.$(close).append(this._button('close',()=>this._closeDialog(id)));
      this.$(id).onclick=e=>{if(e.target===this.$(id))this._closeDialog(id);};
      this.$(id).onkeydown=e=>{if(e.key==='Escape'){e.stopPropagation();this._closeDialog(id);}if(e.key==='Tab'){
        const inputs=[...this.$(id).querySelectorAll('button,input,select,summary')].filter(x=>!x.disabled&&x.getClientRects().length);
        const first=inputs[0],last=inputs.at(-1),active=this.shadowRoot.activeElement;
        if(e.shiftKey&&active===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&active===last){e.preventDefault();first?.focus();}
      }};
    }
    this._renderNav();this._renderBrowse();this._renderContent();
  }
  get _isFullscreen(){return this.getRootNode().fullscreenElement===this;}
  _openExpanded(){
    if(!this._compactHome)return;
    const dialog=this.$('expanded-dialog'),frame=this.$('expanded-frame'),shell=this.shadowRoot.querySelector('.shell');
    this._expandOpener=this.shadowRoot.activeElement;this._savedMinHeight=this.style.minHeight;this.style.minHeight=`${shell.offsetHeight}px`;
    this._expanded=true;frame.append(shell);shell.classList.remove('compact');dialog.showModal();
    this._expandedResize=new ResizeObserver(()=>{const height=Math.max(0,frame.clientHeight-44),value=`${height}px`;if(shell.style.getPropertyValue('--fn-height')!==value)shell.style.setProperty('--fn-height',value);});
    this._expandedResize.observe(frame);this._key='';this._lyricKey='';
  }
  async _closeExpanded(){
    if(this._isFullscreen)await this._toggleFullscreen();
    this._finishExpanded();
  }
  _finishExpanded(focus=true){
    if(!this._expanded)return;
    this._expanded=false;this._expandedResize?.disconnect();this._expandedResize=null;
    this._stopViewTransition();this._clearLyricInteraction();this._closeVolume();this._queueOpen=false;
    const shell=this.shadowRoot.querySelector('.shell');this.$('expanded-dialog').close();this.shadowRoot.insertBefore(shell,this.$('expanded-dialog'));
    shell.style.removeProperty('--fn-height');this.style.minHeight=this._savedMinHeight||'';this._tab='browse';this._renderContent();this._animate();
    if(focus&&this._connected)this._expandOpener?.focus();this._expandOpener=null;
  }
  _syncFullscreen(){
    const button=this.$('now-fullscreen');if(!button)return;
    const active=this._isFullscreen,key=active?'exitFullscreen':'fullscreen';
    button.hidden=this._compactHome||this._tab!=='lyrics';button.disabled=!this.ownerDocument.fullscreenEnabled;
    button.title=this.t(key);button.setAttribute('aria-label',this.t(key));button.setAttribute('aria-pressed',String(active));
    button.querySelector('feiniu-icon').setAttribute('icon',`mdi:${icons[key]}`);
  }
  async _toggleFullscreen(){
    try{if(this._isFullscreen)await this.ownerDocument.exitFullscreen();else await (this._expanded?this.$('expanded-frame'):this).requestFullscreen();}
    catch{this._text('error',this.t('fullscreenError'));}
    this._syncFullscreen();
  }
  _closeDialog(id){this.$(id).hidden=true;this._dialogOpener?.focus();}
  _closeVolume(focus=false){const pop=this.$('volume-pop');if(!pop||pop.hidden)return;pop.hidden=true;this.$('volume-toggle').setAttribute('aria-expanded','false');if(focus)this.$('volume-toggle').focus();}
  _toggleVolume(){const opening=this.$('volume-pop').hidden;this.$('volume-pop').hidden=!opening;this.$('volume-toggle').setAttribute('aria-expanded',String(opening));if(opening)this.$('volume').focus();}
  _closeQueue(focus=false){if(!this._queueOpen)return;this._queueOpen=false;this._renderContent();if(focus)this.$('now-queue').focus();}
  _stopViewTransition(){
    this._viewEpoch=(this._viewEpoch||0)+1;
    for(const animation of this._viewAnimations||[])animation.cancel();this._viewAnimations=[];
  }
  async _transitionPlayer(entering,start){
    if(document.hidden||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    // Animate only composited content, never HA's grid, padding or dimensions.
    const from=entering?{opacity:0,transform:'translateY(24px)'}:{opacity:1,transform:'translateY(0)'};
    const to=entering?{opacity:1,transform:'translateY(0)'}:{opacity:0,transform:'translateY(24px)'};
    this._viewAnimations=[...this.shadowRoot.querySelectorAll('.now-info,.lyric-panel,.dock,#now-back,#now-queue,#now-fullscreen')]
      .filter(e=>!e.hidden).map(e=>e.animate([start.get(e)||from,to],{duration:entering?240:180,easing:'cubic-bezier(.2,.7,.2,1)',fill:'both'}));
    await Promise.allSettled(this._viewAnimations.map(a=>a.finished));
  }
  async _showTab(key,load=true){
    const expanding=this._compactHome;if(expanding)this._openExpanded();
    const start=new Map((this._viewAnimations||[]).map(a=>{const e=a.effect.target,s=getComputedStyle(e);return [e,{opacity:s.opacity,transform:s.transform}];}));
    this._stopViewTransition();const epoch=this._viewEpoch;
    const leaving=this._tab==='lyrics'&&key!=='lyrics',entering=this._tab!=='lyrics'&&key==='lyrics';
    if(leaving){await this._transitionPlayer(false,start);if(epoch!==this._viewEpoch||!this._connected)return;}
    if(key!=='lyrics'&&this._isFullscreen){await this._toggleFullscreen();if(epoch!==this._viewEpoch||!this._connected)return;}
    for(const a of this._viewAnimations)a.cancel();this._viewAnimations=[];
    this._clearLyricInteraction();this._lastLine=-1;this._queueOpen=false;this._closeVolume();this._text('error','');this._tab=key;this._renderContent();this.$('main').scrollTop=0;
    if(expanding)this._render();
    if(key==='browse'&&load&&!this._browseResult&&!this._browseStarted)this._browse();this._animate();this._queueLyricPaint(true);
    if(entering){await this._transitionPlayer(true,start);if(epoch===this._viewEpoch){for(const a of this._viewAnimations)a.cancel();this._viewAnimations=[];}}
  }
  _paintImage(id,value){const img=this.$(id),url=safeImage(value);if(url&&img.getAttribute('src')!==url){img.src=url;img.hidden=false;img.previousElementSibling.hidden=true;}if(!url){img.removeAttribute('src');img.hidden=true;img.previousElementSibling.hidden=false;}}
  _paintCompactBackground(value){
    if(!this._compactHome||this._config.compact_background!=='artwork')return;
    const url=safeImage(value);if(url===this._compactArtURL)return;this._compactArtURL=url;
    const layers=[...this.$('compact-background').children];
    if(!url){layers.forEach(img=>{img.classList.remove('visible');img.removeAttribute('src');});return;}
    // Two reused image layers crossfade only after the next cached artwork is ready.
    // No palette API, canvas extraction or repeated work on progress updates.
    const next=layers.find(img=>!img.classList.contains('visible'))||layers[0];
    next.onload=()=>{if(!next.isConnected||this._compactArtURL!==url)return;for(const img of layers)img.classList.toggle('visible',img===next);};
    next.onerror=()=>{if(this._compactArtURL===url)layers.forEach(img=>img.classList.remove('visible'));};
    next.src=url;if(next.complete&&next.naturalWidth>0)next.onload();
  }
  _render() {
    if (!this.$('heading') || !this._hass) return;
    if(this._language!==(this._hass.language||'en'))this._build();
    const state=this._state,a=this._attrs;
    if(this._offsetEdit&&((a.lyric_offset||0)!==this._offsetEdit.base||(a.lyric_offset||0)===this._offsetEdit.value))this._offsetEdit=null;
    this._text('heading',this._config.title || (this._hass.language?.startsWith('zh')?'飞牛音乐':'FeiNiu Music'));
    this._text('compact-title',this.$('heading').textContent);this._text('expanded-title',this.$('heading').textContent);
    this._text('output',this._hass.states[a.output_player]?.attributes.friendly_name || this.t('source'));this.$('output').title=this.$('output').textContent;
    this._text('compact-output',this.$('output').textContent);
    this.shadowRoot.querySelector('.shell').dataset.theme=this._config.theme==='auto'?(this._hass.themes?.darkMode?'dark':'light'):(this._config.theme||'dark');
    this.$('expanded-dialog').dataset.theme=this.shadowRoot.querySelector('.shell').dataset.theme;
    this._text('title',a.media_title || this.t('unknown')); this._text('artist',a.media_artist); this._text('album',a.media_album_name);
    this._text('mini-title',a.media_title||this.t('unknown'));this._text('mini-artist',a.media_artist||this.t('empty'));
    const ambient=safeImage(a.entity_picture||a.media_image_url);if(ambient&&this.$('ambient').getAttribute('src')!==ambient)this.$('ambient').src=ambient;this.$('ambient').hidden=!ambient;
    for(const id of ['art','mini-art'])this._paintImage(id,a.entity_picture||a.media_image_url);
    const offline=!state || state.state==='unavailable';
    let message=offline ? this.t('offline') : this.t(a.session_reason in words.en ? a.session_reason : (a.session_phase || 'idle'));
    if(a.position_source==='estimated')message+=` · ${this.t('estimated')}`;
    this.$('output').classList.toggle('offline',offline);
    this._text('status',offline||['failed','detached'].includes(a.session_phase)?message:'');
    const playing=state?.state==='playing', flags=a.supported_features || 0;
    this._buttons.play.firstChild.setAttribute('icon',`mdi:${playing?'pause':'play'}`);
    this._buttons.play.title=this.t(playing?'pause':'play');this._buttons.play.setAttribute('aria-label',this._buttons.play.title);
    for(const [key,b] of Object.entries(this._buttons)) b.disabled=offline || (key==='play' && playing && !(flags&1));
    this._buttons.stop.disabled=!(a.queue_length || a.session_phase==='loading');
    const mode=PLAYBACK_MODES[playbackMode(a)];
    for(const b of this.shadowRoot.querySelectorAll('[data-mode]')){
      b.title=this.t(mode.label);b.setAttribute('aria-label',b.title);b.disabled=offline||!!this._modePending;
      b.firstChild.setAttribute('icon',`mdi:${mode.icon}`);
    }
    this.shadowRoot.querySelector('.dock-stop').disabled=this._buttons.stop.disabled||offline;
    this.$('seek').disabled=offline || !(flags&2) || !a.queue_active || !a.media_duration;
    this.$('seek').max=String(a.media_duration || 100);this._text('duration',timeLabel(a.media_duration));
    this.$('volume').disabled=offline || !(flags&4);this.$('volume-toggle').disabled=this.$('volume').disabled;
    if(this.shadowRoot.activeElement!==this.$('volume')){this.$('volume').value=String(a.volume_level||0);this._text('volume-value',`${Math.round((a.volume_level||0)*100)}%`);}
    const anchorKey=[a.media_position,a.media_position_updated_at,state?.state].join('|');
    if(anchorKey!==this._anchorKey){this._anchorKey=anchorKey;this._anchor={value:positionAt(a,state?.state,Date.now()),at:performance.now(),moving:playing};}
    const key=`${this._config.entity}/${a.queue_revision}/${JSON.stringify(a.playback_profile)}`;
    if(key!==this._key){this._key=key;this._refreshQueue();}
    const lyricKey=`${this._config.entity}/${a.playback_round}/${a.queue_item_id}`;
    if(lyricKey!==this._lyricKey){this._lyricKey=lyricKey;this._refreshLyrics();}
    if(!this._compactHome&&this._tab==='browse'&&!this._browseResult&&!this._browseStarted)this._browse();
    this._syncCompact();this._renderLyricTools();this._animate();
  }
  _position() {if(this._anchor?.value==null)return null;return Math.min(this._attrs.media_duration||Infinity,this._anchor.value+(this._anchor.moving?(performance.now()-this._anchor.at)/1000:0));}
  _stopAnimation(){if(this._raf)cancelAnimationFrame(this._raf);this._raf=0;}
  _animate(){
    this._stopAnimation();if(!this._connected||document.hidden)return;
    const tick=()=>{const p=this._position();if(!this._dragging){this.$('seek').value=String(p||0);this._text('elapsed',timeLabel(p));}
      if(this._lyricsVisible){const following=this._attrs.queue_active&&['playing','paused'].includes(this._state?.state)&&!['loading','detached','failed'].includes(this._attrs.session_phase);const i=following&&p!=null?lyricIndex(this._lyrics,p,this._lyricOffset):-1;if(i!==this._lastLine){const first=this._lastLine===-1;this._lastLine=i;const lines=this.shadowRoot.querySelectorAll('#lyric-lines p');lines.forEach((line,index)=>{line.classList.toggle('current',i===index);line.parentElement.classList.toggle('current',i===index);});if(!this._lyricsManual)this._centreLyric(i,!first);}}
      if(this._state?.state==='playing'&&this._connected&&!document.hidden)this._raf=requestAnimationFrame(tick);};tick();
  }
  get _lyricOffset(){return this._offsetEdit?.value??(this._attrs.lyric_offset||0);}
  _clearLyricInteraction(){clearTimeout(this._lyricFollowTimer);clearTimeout(this._lyricNoticeTimer);cancelAnimationFrame(this._lyricPaintRaf);this._lyricPaintRaf=0;this._lyricFollowTimer=0;this._lyricNoticeTimer=0;this._lyricsManual=false;this._selectedLyric=null;this.$('lyric-lines')?.querySelector('.selected')?.classList.remove('selected');this.$('lyric-lines')?.parentElement.classList.remove('lyrics-engaged');if(this.$('lyric-notice'))this._text('lyric-notice','');}
  _holdLyrics(){
    if(!this._lyricsVisible||!this._lyrics.length)return;
    this._lyricsManual=true;this.$('lyric-lines').parentElement.classList.add('lyrics-engaged');clearTimeout(this._lyricFollowTimer);
    this._lyricFollowTimer=setTimeout(()=>{this._lyricFollowTimer=0;if(this._connected&&this._lyricsVisible)this._followLyrics();},8000);
  }
  _followLyrics(){clearTimeout(this._lyricFollowTimer);this._lyricFollowTimer=0;this._lyricsManual=false;this._selectedLyric=null;this.$('lyric-lines').querySelector('.selected')?.classList.remove('selected');this.$('lyric-lines').parentElement.classList.remove('lyrics-engaged');this._centreLyric(this._lastLine,true);}
  _selectLyric(index){
    this._holdLyrics();this._selectedLyric=index;
    [...this.$('lyric-lines').children].forEach((row,i)=>row.classList.toggle('selected',i===index));this._centreLyric(index,true);
  }
  _queueLyricPaint(resized=false){
    this._lyricResized=this._lyricResized||resized;if(this._lyricPaintRaf||!this._connected||document.hidden)return;
    this._lyricPaintRaf=requestAnimationFrame(()=>{this._lyricPaintRaf=0;this._paintLyricDepth();});
  }
  _paintLyricDepth(){
    const box=this.$('lyric-lines');if(!this._lyricsVisible||!box?.clientHeight||!this._lyrics.length)return;
    // Use the allocated panel height so old scroll padding cannot preserve a taller viewport.
    const available=Math.max(0,box.parentElement.getBoundingClientRect().height);
    const padding=`${available/2}px`;if(box.style.getPropertyValue('--lyric-pad')!==padding)box.style.setProperty('--lyric-pad',padding);
    if(this._lyricResized){this._lyricResized=false;if(!this._lyricsManual)this._centreLyric(this._lastLine);else if(this._selectedLyric!=null)this._centreLyric(this._selectedLyric);}
    const rect=box.getBoundingClientRect(),middle=rect.top+rect.height/2;
    // Compact lyrics stay sharp; full-page blur and shared fading follow scroll position.
    // Batch geometry reads before writing styles to avoid repeated layout work.
    const compact=this._compactHome;
    const values=[...box.querySelectorAll('.lyric-row')].map(row=>{const r=row.getBoundingClientRect(),distance=Math.abs(r.top+r.height/2-middle)/(rect.height/2);return [row,`${compact?0:Math.max(0,Math.min(4,(distance-.25)*5)).toFixed(2)}px`,compact?Math.max(.46,.8-distance*.3).toFixed(3):''];});
    for(const [row,blur,opacity] of values){
      if(row.style.getPropertyValue('--lyric-blur')!==blur)row.style.setProperty('--lyric-blur',blur);
      if(row.style.getPropertyValue('--lyric-opacity')!==opacity)row.style.setProperty('--lyric-opacity',opacity);
    }
  }
  _centreLyric(index,smooth=false){
    const box=this.$('lyric-lines'),line=box.children[index];if(!line||!this._lyricsVisible)return;
    const y=line.getBoundingClientRect().top-box.getBoundingClientRect().top+box.scrollTop-box.clientHeight/2+line.clientHeight/2;
    box.scrollTo({top:y,behavior:smooth&&!matchMedia('(prefers-reduced-motion: reduce)').matches?'smooth':'instant'});
    this._queueLyricPaint();
  }
  _renderLyricTools(){
    if(!this.$('lyric-tools'))return;
    this._lyricPanel.classList.toggle('timed-lyrics',!!this._lyrics.length);
    this.$('lyric-tools').hidden=!this._lyrics.length;
    const offset=this._lyricOffset,offline=!this._state||this._state.state==='unavailable';
    this.$('lyricEarlier').disabled=offline||!!this._offsetSaving||offset>=30;
    this.$('lyricLater').disabled=offline||!!this._offsetSaving||offset<=-30;
    const reset=this.$('lyric-offset-value');reset.textContent=`${offset>0?'+':''}${offset.toFixed(1)}s`;reset.disabled=offline||!!this._offsetSaving||offset===0;
    for(const [i,b] of [...this.$('lyric-lines').querySelectorAll('.lyric-seek')].entries()){
      const target=lyricSeekPosition(this._lyrics[i]?.time_ms,offset,this._attrs.media_duration);
      b.disabled=this.$('seek').disabled||!['playing','paused'].includes(this._state?.state)||!!this._lyricSeeking||target===null;
      b.querySelector('span').textContent=timeLabel(target);b.title=b.disabled?this.t('lyricSeekUnavailable'):`${this.t('lyricSeek')} ${timeLabel(target)}`;b.setAttribute('aria-label',b.title);
    }
  }
  async _adjustLyricOffset(step){
    if(this._offsetSaving)return;
    const entity=this._config.entity,edit={base:this._attrs.lyric_offset||0,value:step===0?0:Math.max(-30,Math.min(30,Math.round((this._lyricOffset+step)*10)/10))};
    this._offsetEdit=edit;this._offsetSaving=true;this._renderLyricTools();this._animate();
    try{await this._call('feiniu_music/preferences',{lyric_offset:edit.value});
      if(!this._connected||this._config.entity!==entity)return;
      this._text('lyric-notice',step===0?this.t('lyricDefault'):`${this.t('offset')}: ${edit.value>0?'+':''}${edit.value.toFixed(1)}`);
      clearTimeout(this._lyricNoticeTimer);this._lyricNoticeTimer=setTimeout(()=>{this._lyricNoticeTimer=0;this._text('lyric-notice','');},2000);
    }catch(err){if(this._connected&&this._config.entity===entity){this._offsetEdit=null;this._error(err);}}
    finally{this._offsetSaving=false;if(this._connected){this._renderLyricTools();this._animate();}}
  }
  async _seekLyric(line,key){
    if(this._lyricSeeking||key!==this._lyricKey||this.$('seek').disabled||!['playing','paused'].includes(this._state?.state))return;
    const target=lyricSeekPosition(line.time_ms,this._lyricOffset,this._attrs.media_duration);if(target===null)return;
    const epoch=this._lyricEpoch,paused=this._state.state==='paused';this._lyricSeeking=true;this._renderLyricTools();
    try{if(!await this._service('media_seek',{seek_position:target}))return;
      if(!this._connected||epoch!==this._lyricEpoch||key!==this._lyricKey)return;
      if(paused&&this._state.state==='paused')await this._service('media_play');
      if(this._connected&&epoch===this._lyricEpoch&&key===this._lyricKey)this._followLyrics();
    }finally{this._lyricSeeking=false;if(this._connected)this._renderLyricTools();}
  }
  async _call(type,data={}){return this._hass.callWS({type,entity_id:this._config.entity,...data});}
  _error(err){this.$('error').style.color='var(--error-color,#b62c3d)';this.$('error').setAttribute('role','alert');this._text('error',err?.code==='revision_conflict'?this.t('conflict'):this.t('error'));if(err?.code==='revision_conflict')this._refreshQueue();}
  async _service(service,data={}){this._text('error','');try{await this._hass.callService('media_player',service,{entity_id:this._config.entity,...data});return true;}catch(err){this._error(err);return false;}}
  async _transport(key){
    if(key==='mode'){
      if(this._modePending)return;
      const current={shuffle:!!this._attrs.shuffle,repeat:this._attrs.repeat||'off'};
      const next=PLAYBACK_MODES[(playbackMode(current)+1)%PLAYBACK_MODES.length];
      this._modePending=true;this._render();
      try{
        if(current.shuffle!==next.shuffle&&!await this._service('shuffle_set',{shuffle:next.shuffle}))return;
        if(current.repeat!==next.repeat)await this._service('repeat_set',{repeat:next.repeat});
      }finally{this._modePending=false;this._render();}
      return;
    }
    return this._service({previous:'media_previous_track',next:'media_next_track',stop:'media_stop',play:this._state?.state==='playing'?'media_pause':'media_play'}[key]);
  }
  _refresh(){this._refreshQueue();this._refreshLyrics();}
  async _refreshQueue(){
    if(!this._hass||!this._connected||document.hidden||this._compactHome)return;
    if(this._queuePending){this._queueAgain=true;return;}this._queuePending=true;const epoch=++this._queueEpoch;
    try{const page=await this._call('feiniu_music/queue',{offset:this._offset,limit:25});if(epoch!==this._queueEpoch||!this._connected)return;
      if(page.revision<this._attrs.queue_revision){this._queueAgain=true;return;}this._queue=page;this._text('diagnostics',JSON.stringify(page.diagnostics,null,2));this._renderContent();
    }catch(err){if(epoch===this._queueEpoch)this._error(err);}finally{this._queuePending=false;if(this._queueAgain){this._queueAgain=false;setTimeout(()=>this._refreshQueue(),150);}}
  }
  async _refreshLyrics(){
    if(!this._hass||!this._connected||document.hidden||(this._compactHome&&!['lyrics','auto'].includes(this._config.compact_view)))return;
    const requested=this._lyricKey;
    if(this._lyricResultKey===requested){this._renderLyrics();this._syncCompact();return;}
    if(this._lyricPendingKey===requested)return;
    const epoch=++this._lyricEpoch;this._lyricPendingKey=requested;
    this._lyricResultKey='';this._lyrics=[];this._lyricText='';this._lyricStatus='loading';this._lastLine=-1;
    this._clearLyricInteraction();this._renderLyrics();
    this._syncCompact();
    if(!this._attrs.queue_item_id){this._lyricPendingKey='';this._lyricStatus='noLyrics';this._renderContent();return;}
    try{const result=await this._call('feiniu_music/lyrics',{round:this._attrs.playback_round||0,item_id:this._attrs.queue_item_id});
      if(!this._connected||epoch!==this._lyricEpoch||requested!==this._lyricKey)return;
      this._lyrics=result.synced_lines||[];this._lyricText=result.text||'';this._lyricStatus=this._lyricText||this._lyrics.length?'':'noLyrics';this._lyricResultKey=requested;
    }catch(err){if(epoch!==this._lyricEpoch)return;this._lyricStatus=err?.code==='revision_conflict'?'loading':'lyricError';}
    finally{if(epoch===this._lyricEpoch)this._lyricPendingKey='';}
    this._renderContent();this._animate();
  }
  _syncCompact(){
    if(!this.$('compact-stage'))return;
    const home=this._compactHome,rich=home&&this._compactRich,stage=this.$('compact-stage'),panel=this._lyricPanel;
    this.shadowRoot.querySelector('.shell').dataset.compactBackground=this._config.compact_background||'default';
    this.shadowRoot.querySelector('.shell').dataset.compactMask=this._config.compact_mask||'soft';
    this._paintCompactBackground(this._attrs.entity_picture||this._attrs.media_image_url);
    const parent=rich?stage:this.$('now-view');if(panel.parentElement!==parent){parent.append(panel);this._queueLyricPaint(true);}
    const a=this._attrs,phase=a.session_phase,hasTrack=!!a.queue_item_id;
    const unavailable=!this._state||this._state.state==='unavailable';
    const show=rich;
    if(this._compactShowLyrics!==show){this._compactShowLyrics=show;this._lastLine=-1;this._queueLyricPaint(true);}
    panel.hidden=home&&!show;stage.hidden=!rich;
    const shell=this.shadowRoot.querySelector('.shell');shell.classList.toggle('compact-rich',rich);
    const loading=phase==='loading'&&!(show&&this._lyricStatus==='loading');
    const caption=unavailable?'compactOffline':!hasTrack?'compactEmpty':phase==='detached'?'compactDetached':phase==='failed'?'compactFailed':loading?'compactLoading':phase!=='loading'&&show&&this._lyrics.length&&this._position()==null?'compactWaiting':'';
    const status=this.$('compact-status'),text=home&&caption?this.t(caption):'';
    status.hidden=!text;this._text('compact-status',text);status.title=text;status.classList.toggle('loading',caption==='compactLoading');
  }
  _empty(text){const p=document.createElement('div');p.className='empty';p.textContent=text;return p;}
  _renderContent(){
    const root=this.$('content');if(!root)return;
    this.shadowRoot.querySelector('.shell').classList.toggle('compact',this._compactHome);
    this.shadowRoot.querySelector('.shell').classList.toggle('now-open',!this._compactHome&&this._tab==='lyrics');this.$('now-back').hidden=this._compactHome||this._tab!=='lyrics';this.$('now-queue').hidden=this._compactHome||this._tab!=='lyrics';
    this.$('browser').hidden=this._tab!=='browse';this.$('queue-view').hidden=this._tab!=='queue'&&!(this._tab==='lyrics'&&this._queueOpen);this.$('queue-close').hidden=!(this._tab==='lyrics'&&this._queueOpen);this.$('now-queue').setAttribute('aria-expanded',String(!!this._queueOpen));this.$('now-view').hidden=this._tab!=='lyrics';
    this._syncNavigation();
    this._syncCompact();this._syncFullscreen();this._renderLyrics();
    if(this.$('queue-view').hidden)return;
    if(!this._queue){root.replaceChildren(this._empty(this.t('loading')));return;}
    if(!this._queue.total){root.replaceChildren(this._empty(this.t('empty')),this._button('browse',()=>this._showTab('browse'),this.t('browse')));this._queueRows=new Map();return;}
    this._text('queue-hint',`${this._queue.total} ${this.t('count')} · ${this.t('queueHint')}`);
    const old=this._queueRows||new Map(),nextRows=new Map();
    this._queue.items.forEach((item,index)=>{
      let row=old.get(item.item_id);
      if(!row){
        row=document.createElement('div');row.dataset.itemId=item.item_id;const number=document.createElement('span');number.className='number';row.append(number);
        const cover=this._button('track',()=>this._edit('jump',item.item_id));cover.className='row-cover queue-art';row.append(cover);
        const name=this._button('jump',()=>this._edit('jump',item.item_id));name.className='name';row.append(name);
        const actions=document.createElement('div');actions.className='actions';
        const position=()=>this._queue.items.findIndex(x=>x.item_id===item.item_id);
        actions.append(this._button('up',()=>this._edit('move',item.item_id,this._queue.items[position()-1]?.item_id)),
          this._button('down',()=>this._edit('move',item.item_id,this._queue.items[position()+2]?.item_id||null)),
          this._button('remove',()=>this._edit('remove',item.item_id)));row.append(actions);
      }
      row.className=`row queue-row${item.current?' current':''}`;row.querySelector('.number').textContent=item.current?'♫':this._offset+index+1;
      this._rowImage(row,item.thumbnail);
      const cover=row.querySelector('.queue-art');cover.title=`${this.t('jump')} · ${item.title}`;cover.setAttribute('aria-label',cover.title);
      const name=row.querySelector('.name');name.replaceChildren();const title=document.createElement('span');title.className='row-title';title.textContent=item.title;name.append(title);name.setAttribute('aria-label',`${this.t('jump')} · ${item.title}`);
      const sub=document.createElement('small');sub.textContent=item.artist||'';name.append(sub);
      const absolute=this._offset+index,pending=absolute>this._queue.position,buttons=row.querySelectorAll('.actions button');
      buttons[0].disabled=!pending||index===0||absolute<=this._queue.position+1;
      buttons[1].disabled=!pending||index>=this._queue.items.length-1;
      nextRows.set(item.item_id,row);
    });
    for(const child of [...root.children])if(!nextRows.has(child.dataset.itemId))child.remove();
    [...nextRows.values()].forEach((row,index)=>{if(root.children[index]!==row)root.insertBefore(row,root.children[index]||null);});
    this._queueRows=nextRows;
    const pager=document.createElement('div');pager.className='pager';const back=this._button('pagePrevious',()=>{this._offset=Math.max(0,this._offset-25);this._refreshQueue();});back.disabled=this._offset===0;
    const count=document.createElement('span');count.textContent=`${this._queue.total} ${this.t('count')}`;
    const next=this._button('pageNext',()=>{this._offset+=25;this._refreshQueue();});next.disabled=this._offset+25>=this._queue.total;
    pager.append(count,back,next);root.append(pager);
  }
  _rowImage(row,value){
    const target=row.querySelector('.queue-art'),icon=target.querySelector('feiniu-icon');
    const url=safeImage(value);let img=target.querySelector('img');
    if(!url){img?.remove();icon.hidden=false;return;}
    if(!img){img=document.createElement('img');img.alt='';img.loading='lazy';img.decoding='async';img.onerror=()=>{img.hidden=true;icon.hidden=false;};target.append(img);}
    if(img.getAttribute('src')!==url){img.src=url;img.hidden=false;icon.hidden=true;}
  }
  async _edit(action,itemId,beforeId){if(!this._queue)return;this._text('error','');try{await this._call('feiniu_music/edit_queue',{action,revision:this._queue.revision,...(itemId?{item_id:itemId}:{}),...(beforeId!==undefined?{before_id:beforeId}:{})});this._refreshQueue();}catch(err){this._error(err);}}
  _renderLyrics(){
    const key=[this._lyricKey,this._lyricStatus,this._lyricText,JSON.stringify(this._lyrics)].join('|');if(key===this._lyricsPaintKey)return;this._lyricsPaintKey=key;
    const box=this.$('lyric-lines');box.replaceChildren();box.classList.toggle('timed',this._lyrics.length>0);
    const plain=!!this._lyricText&&!this._lyrics.length;box.title=plain?this.t('plainLyrics'):'';box.setAttribute('aria-label',this.t(plain?'plainLyrics':'lyricLabel'));box.scrollTop=0;
    if(this._lyrics.length){const requested=this._lyricKey;for(const [index,line] of this._lyrics.entries()){
      const row=document.createElement('div');row.className='lyric-row';const p=document.createElement('p');p.textContent=line.text;
      p.tabIndex=0;p.setAttribute('role','button');p.title=this.t('lyricCentre');p.onclick=()=>this._selectLyric(index);p.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();this._selectLyric(index);}};
      const b=this._button('jump',()=>this._seekLyric(line,requested));b.className='lyric-seek';b.append(document.createElement('span'));row.append(p,b);box.append(row);
    }}
    else if(plain){const text=document.createElement('div');text.className='plain-lyrics';for(const line of this._lyricText.split(/\r?\n/)){const p=document.createElement('p');p.textContent=line;text.append(p);}box.append(text);}
    else box.append(this._empty(this.t(this._lyricStatus||'noLyrics')));this._lastLine=-1;this._renderLyricTools();this._queueLyricPaint(true);
  }
  _label(item){const key=String(item?.title||'').toLowerCase();return ['tracks','albums','artists','playlists'].includes(key)&&item?.media_class==='directory'?this.t(key):item?.title||this.t('browse');}
  _syncNavigation(){
    for(const b of this.shadowRoot.querySelectorAll('[data-tab]'))b.setAttribute('aria-selected',String(b.dataset.tab===this._tab));
    const current=this._tab==='browse'&&!this._compactHome&&!this._browseQuery?this._browseItem?.media_content_id:'';
    for(const b of this.shadowRoot.querySelectorAll('[data-browse-root]')){
      const root=b.dataset.browseRoot,active=!!current&&(current===root||current.startsWith(`${root}/`));
      b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
    }
  }
  _renderNav(){
    for(const id of ['categories','mobile-categories']){
      const nav=this.$(id);nav.replaceChildren();for(const item of this._roots){const b=this._button(mediaKind(item),()=>{this._showTab('browse',false);this._browseStack=[];this._browse(item);},this._label(item));b.dataset.browseRoot=item.media_content_id;nav.append(b);}
    }
    const nav=this.$('playlist-nav');nav.replaceChildren();for(const item of (this._playlistRows||[]).slice(0,12)){
      const b=this._button('playlist',()=>{this._showTab('browse',false);this._browse(item);});b.setAttribute('aria-label',item.title);const thumb=safeImage(item.thumbnail);if(thumb){b.replaceChildren();const img=document.createElement('img');img.src=thumb;img.alt='';img.loading='lazy';b.append(img);}const label=document.createElement('span');label.className='name';label.textContent=item.title;b.append(label);nav.append(b);
    }
    this._syncNavigation();
  }
  async _loadPlaylists(){
    const item=this._roots.find(x=>mediaKind(x)==='playlist');if(!item||this._playlistRows)return;
    const entity=this._config.entity;
    try{const result=await this._call('media_player/browse_media',{media_content_id:item.media_content_id,media_content_type:item.media_content_type});if(this._connected&&entity===this._config.entity){this._playlistRows=result.children||[];this._renderNav();}}
    catch{/* Optional sidebar shortcuts. Opening Playlists retains the normal error/retry UI. */}
  }
  async _browse(item=null,push=true,query=''){
    if(!this._hass)return;const epoch=++this._browseEpoch;this._browseStarted=true;this._browseLoading=true;this._browseError=false;
    this.$('browse-list').replaceChildren(this._empty(this.t('loading')));this.$('browse-all').replaceChildren();
    try{
      const data=item?{media_content_id:item.media_content_id,media_content_type:item.media_content_type}:{};
      let result=await this._call(query?'media_player/search_media':'media_player/browse_media',{...data,...(query?{search_query:query}:{})});
      if(epoch!==this._browseEpoch||!this._connected)return;
      if(query)result={title:query,children:result.result||[]};
      if(!item&&!query){this._roots=result.children||[];this._renderNav();this._loadPlaylists();}
      if(!query)this.$('search').value='';this._browseItem=item;this._browseResult=result;this._browseQuery=query;this._browseLoading=false;
      const frame={item,query};if(push)this._browseStack.push(frame);else if(this._browseStack.length)this._browseStack[this._browseStack.length-1]=frame;
      // The artist response contains the actual relation links; do not invent endpoints.
      if(mediaKind(item)==='artist'&&(result.children||[]).some(x=>x.media_class==='directory')){
        this._artistContext={item,links:result.children};const tracks=result.children.find(x=>String(x.title).toLowerCase()==='tracks');if(tracks){await this._browse(tracks,false);return;}
      }
      this._renderNav();this._renderBrowse();this.$('main').scrollTop=0;
      if(!item&&!query){const first=this._roots.find(x=>mediaKind(x)==='album');if(first)await this._browse(first,false);}
    }catch(err){if(epoch===this._browseEpoch){this._browseLoading=false;this._browseError=true;this._failedBrowse={item,push,query};this.$('browse-list').replaceChildren(this._empty(this.t('error')),this._button('retry',()=>this._browse(item,push,query),this.t('retry')));}}
    finally{if(epoch===this._browseEpoch)this._browseStarted=false;}
  }
  _back(){this._browseStack.pop();const frame=this._browseStack.at(-1);this._browse(frame?.item||null,false,frame?.query||'');}
  _cover(container,item){
    const url=safeImage(item?.thumbnail);const icon=document.createElement('feiniu-icon');icon.setAttribute('icon',`mdi:${icons[mediaKind(item)]||'music-note'}`);container.append(icon);
    if(url){const img=document.createElement('img');img.alt='';img.loading='lazy';img.decoding='async';img.src=url;icon.hidden=true;img.onerror=()=>{img.hidden=true;icon.hidden=false;};container.append(img);}
  }
  _renderBrowse(){
    if(!this.$('browse-list')||this._browseLoading||this._browseError)return;
    this._text('error','');
    const result=this._browseResult,item=this._browseItem,query=this._browseQuery,children=result?.children||[];
    const heading=this.$('browse-heading'),list=this.$('browse-list'),crumb=this.$('breadcrumbs'),relations=this.$('relations');heading.replaceChildren();list.replaceChildren();crumb.replaceChildren();relations.replaceChildren();relations.hidden=true;this.$('browse-all').replaceChildren();
    if(!result){list.append(this._empty(this.t('loading')));return;}
    const root=this._button('browse',()=>{this._browseStack=[];this._browse();},this.t('browse'));crumb.append(root);const current=document.createElement('span');current.textContent=`/  ${query?this.t('results'):this._label(item||result)}`;crumb.append(current);
    this.$('browse-back').firstChild.disabled=this._browseStack.length<=1;
    const artist=this._artistContext&&item?.media_content_id?.startsWith(this._artistContext.item.media_content_id+'/')?this._artistContext:null;
    const owner=artist?.item||item;const detailed=owner&&['album','artist','playlist'].includes(owner.media_class);
    this.shadowRoot.querySelector('.shell').classList.toggle('detail-open',!!item&&['album','artist','playlist'].includes(item.media_class));
    const title=document.createElement('h1');title.textContent=query?query:this._label(owner||result);
    const count=document.createElement('p');count.className='muted';count.textContent=`${children.length} ${this.t('count')}`;
    const actions=document.createElement('div');actions.className='hero-actions';
    if(result.can_play){const play=this._button('play',()=>this._select(result,'replace'),this.t('browseAll'));play.className='pill primary';const add=this._button('add',()=>this._select(result,'add'),this.t('add'));add.className='pill secondary-add';actions.append(play,add);}
    if(detailed){
      heading.className=`hero ${mediaKind(owner)}`;const art=document.createElement('div');art.className='hero-cover';this._cover(art,owner);const info=document.createElement('div'),label=document.createElement('p');label.className='eyebrow';label.textContent=this.t(mediaKind(owner));info.append(label,title,count,actions);heading.append(art,info);
    }else{heading.className='page-heading';const info=document.createElement('div');info.append(title,count);heading.append(info,actions);}
    if(artist){relations.hidden=false;for(const link of artist.links){const b=this._button('related',()=>this._browse(link,false),this._label(link));b.classList.toggle('active',link.media_content_id===item.media_content_id);relations.append(b);}}
    if(!children.length){list.className='';list.append(this._empty(this.t(query?'noResults':'emptyQueue')));return;}
    const grid=children.every(x=>['album','artist','playlist'].includes(x.media_class));
    const folders=children.every(x=>x.media_class==='directory');list.className=grid?'cover-grid':folders?'category-grid':'track-list';
    if(!grid&&!folders){const labels=document.createElement('div');labels.className='list-heading';for(const text of ['#',this.t('name'),this.t('actions')]){const span=document.createElement('span');span.textContent=text;labels.append(span);}list.append(labels);}
    children.forEach((child,index)=>{
      if(folders){list.append(this._button(mediaKind(child),()=>this._browse(child),this._label(child)));return;}
      if(grid){const tile=document.createElement('div');tile.className=`tile ${mediaKind(child)}`;const open=this._button('browse',()=>this._browse(child));open.className='tile-open';open.setAttribute('aria-label',child.title);open.replaceChildren();const art=document.createElement('span');art.className='tile-art';this._cover(art,child);const name=document.createElement('span');name.className='tile-title';name.textContent=child.title;const sub=document.createElement('small');sub.textContent=this.t(mediaKind(child));open.append(art,name,sub);tile.append(open);list.append(tile);return;}
      const row=document.createElement('div');row.className='row';
      const number=child.can_play?this._button('play',()=>this._select(child,'replace')):document.createElement('span');number.className='number row-play';number.textContent=String(index+1);if(child.can_play)number.setAttribute('aria-label',`${this.t('play')} · ${child.title}`);row.append(number);
      const name=this._button('trackInfo',()=>child.can_expand?this._browse(child):this._openTrack(child));name.className='name';name.setAttribute('aria-label',child.title);name.replaceChildren();const title=document.createElement('span');title.className='row-title';title.textContent=child.title;name.append(title);if(child.artist){const artist=document.createElement('small');artist.textContent=child.artist;name.append(artist);}row.append(name);
      const cover=this._button(mediaKind(child),()=>child.can_expand?this._browse(child):child.can_play?this._select(child,'replace'):this._openTrack(child));cover.className='row-cover';cover.replaceChildren();this._cover(cover,child);cover.title=child.can_expand?child.title:`${this.t(child.can_play?'play':'trackInfo')} · ${child.title}`;cover.setAttribute('aria-label',cover.title);row.insertBefore(cover,name);
      if(child.can_play){const a=document.createElement('div');a.className='actions';a.append(this._button('more',()=>this._openTrack(child),this.t('actions')));row.append(a);}list.append(row);
    });
  }
  _openTrack(item){
    this._dialogOpener=this.shadowRoot.activeElement;this.$('track-sheet').hidden=false;this._text('track-detail-title',item.title);this._text('track-detail-sub',item.artist||this.t('track'));this.$('track-detail-art').replaceChildren();this._cover(this.$('track-detail-art'),item);
    this.$('track-actions').replaceChildren();for(const [key,enqueue]of [['play','replace'],['add','add'],['playnext','next']]){const b=this._button(key,async()=>{if(await this._select(item,enqueue)){this._closeDialog('track-sheet');if(enqueue==='replace')this._showTab('lyrics');}},this.t(key));b.className=`pill${enqueue==='replace'?' primary':''}`;this.$('track-actions').append(b);}this.$('track-close').firstChild.focus();
  }
  async _select(item,enqueue){const ok=await this._service('play_media',{media_content_type:item.media_content_type,media_content_id:item.media_content_id,enqueue});if(ok)this._refreshQueue();return ok;}
  _preferences(){
    const box=this.$('preferences');if(!box.hidden){this._closeDialog('preferences');return;}this._dialogOpener=this.shadowRoot.activeElement;box.hidden=false;
    const fields=this.$('preference-fields');fields.replaceChildren();const profile=this._attrs.playback_profile||this._queue?.diagnostics?.profile||{confirmation:'delivery',play_once:false,end_state:'idle',weak_end:false};
    const label=(key,input)=>{const l=document.createElement('label');l.textContent=this.t(key);l.append(input);fields.append(l);};
    const offset=document.createElement('input');offset.type='number';offset.min='-30';offset.max='30';offset.step='.1';offset.id='offset';offset.value=String(this._attrs.lyric_offset||0);label('offset',offset);
    const select=(key,id,choices,value)=>{const input=document.createElement('select');input.id=id;for(const [v,t]of choices){const o=document.createElement('option');o.value=v;o.textContent=t;input.append(o);}input.value=value;label(key,input);};
    select('confirmation','confirmation',[['delivery',this.t('delivery')],['reported',this.t('reported')]],profile.confirmation);
    select('end','end-state',[['idle','IDLE'],['paused','PAUSED'],['off','OFF']],profile.end_state);
    for(const [key,id,value] of [['playOnce','play-once',profile.play_once],['weak','weak-end',profile.weak_end]]){const input=document.createElement('input');input.type='checkbox';input.id=id;input.checked=value;label(key,input);}
    for(const id of ['confirmation','end-state','play-once','weak-end'])this.$(id).disabled=!this._hass.user?.is_admin;
    this.$('save-preferences').replaceChildren(this._button('save',async()=>{try{
      const edited={confirmation:this.$('confirmation').value,play_once:this.$('play-once').checked,end_state:this.$('end-state').value,weak_end:this.$('weak-end').checked};
      const changes=Object.fromEntries(Object.entries(edited).filter(([key,value])=>value!==profile[key]));
      await this._call('feiniu_music/preferences',{lyric_offset:Number(this.$('offset').value),...(this._hass.user?.is_admin&&Object.keys(changes).length?{profile:changes}:{})});
      this.$('error').style.color='var(--secondary-text-color,#5d707b)';this.$('error').setAttribute('role','status');this._text('error',this.t('saved'));this._closeDialog('preferences');this._refreshQueue();}catch(err){this._error(err);}}));this.$('settings-close').firstChild.focus();
  }
}
if(globalThis.customElements&&!customElements.get('feiniu-music-card')){
  customElements.define('feiniu-music-card',FeiNiuMusicCard);
  window.customCards=window.customCards||[];window.customCards.push({type:'feiniu-music-card',name:'FeiNiu Music',description:'Music library, now playing and independent output queue',preview:true});
}
