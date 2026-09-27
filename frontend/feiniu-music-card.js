// FeiNiu queue card: HA owns playback, this component only renders and sends user actions.
export const VERSION = '0.2.0';
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
const words = {
  en: { queue: 'Queue', lyrics: 'Lyrics', browse: 'Choose music', empty: 'Choose an album, playlist or track to begin.',
    next: 'Next', previous: 'Previous', play: 'Play / retry', pause: 'Pause', stop: 'Stop', shuffle: 'Shuffle', repeat: 'Repeat',
    volume: 'Volume', seek: 'Playback position', clear: 'Clear queue', more: 'Next page', back: 'Back',
    remove: 'Remove', up: 'Move earlier', down: 'Move later', jump: 'Play this item', add: 'Add to queue', playnext: 'Play next',
    search: 'Search music', searchGo: 'Search', loading: 'Loading…', noLyrics: 'No lyrics for this track.', lyricError: 'Lyrics unavailable. Playback is unaffected.',
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
    volume: '音量', seek: '播放进度', clear: '清空队列', more: '下一页', back: '返回',
    remove: '移除', up: '向前移动', down: '向后移动', jump: '播放这一项', add: '加入队列', playnext: '下一首播放',
    search: '搜索音乐', searchGo: '搜索', loading: '正在加载…', noLyrics: '这首歌暂无歌词。', lyricError: '歌词暂时不可用，不影响播放。',
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
const icons = { previous: 'skip-previous', play: 'play', pause: 'pause', next: 'skip-next', stop: 'stop', shuffle: 'shuffle', repeat: 'repeat',
  browse: 'music-box-multiple-outline', settings: 'tune-variant', remove: 'close', up: 'arrow-up', down: 'arrow-down', add: 'playlist-plus', playnext: 'playlist-play', back: 'arrow-left' };
const Base = globalThis.HTMLElement || class {};
// Simple geometric playback controls; no icon font or private HA component imports.
const glyphs = {
  play:'M8 4L20 12L8 20Z', pause:'M7 5V19M17 5V19', stop:'M6 6H18V18H6Z',
  'skip-next':'M5 5L15 12L5 19ZM19 5V19', 'skip-previous':'M19 5L9 12L19 19ZM5 5V19',
  shuffle:'M3 6H6C12 6 12 18 18 18H21M18 15L21 18L18 21M3 18H6C12 18 12 6 18 6H21M18 3L21 6L18 9',
  repeat:'M5 8H19V15M16 12L19 15L22 12M19 18H5V11M2 14L5 11L8 14',
  'music-box-multiple-outline':'M5 3H21V19H5ZM2 7V22H17M13 7V15M13 7L18 6M10 15H13V17H10Z',
  'tune-variant':'M3 6H21M3 12H21M3 18H21M8 3V9M16 9V15M10 15V21',
  close:'M6 6L18 18M6 18L18 6', 'arrow-up':'M12 20V4M5 11L12 4L19 11',
  'arrow-down':'M12 4V20M5 13L12 20L19 13', 'arrow-left':'M20 12H4M11 5L4 12L11 19',
  'playlist-plus':'M3 5H16M3 10H16M3 15H10M17 13V21M13 17H21',
  'playlist-play':'M3 5H17M3 10H17M3 15H10M15 13L22 17L15 21Z',
  'music-note':'M11 5V17M11 5L20 3V15M5 17H11V21H5ZM14 15H20V19H14Z',
};
class FeiNiuIcon extends Base {
  static get observedAttributes(){return ['icon'];}
  connectedCallback(){this.paint();}
  attributeChangedCallback(){this.paint();}
  paint(){
    if(!this.shadowRoot)this.attachShadow({mode:'open'});
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
    svg.style.cssText='display:block;width:var(--mdc-icon-size,23px);height:var(--mdc-icon-size,23px);margin:auto';
    const path=document.createElementNS(svg.namespaceURI,'path');
    path.setAttribute('d',glyphs[(this.getAttribute('icon')||'').replace('mdi:','')]||glyphs['music-note']);
    path.setAttribute('fill','none');path.setAttribute('stroke','currentColor');path.setAttribute('stroke-width','1.8');path.setAttribute('stroke-linecap','round');path.setAttribute('stroke-linejoin','round');
    svg.append(path);this.shadowRoot.replaceChildren(svg);
  }
}
if(globalThis.customElements&&!customElements.get('feiniu-icon'))customElements.define('feiniu-icon',FeiNiuIcon);
export class FeiNiuMusicCard extends Base {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this._tab = 'queue'; this._offset = 0; this._queue = null; this._queueEpoch = 0; this._lyricEpoch = 0;
    this._connected = false; this._busy = false; this._lyrics = []; this._lyricText = ''; this._lastLine = -1;
    this._browseStack = []; this._browseEpoch = 0; this._queuePending = false; this._queueAgain = false;
    this._visibility = () => { if (document.hidden) this._stopAnimation(); else { this._refresh(); this._animate(); } };
  }
  setConfig(config) {
    if (!config.entity || !config.entity.startsWith('media_player.')) throw new Error('Choose a FeiNiu media_player entity');
    this._queueEpoch++; this._lyricEpoch++; this._browseEpoch++; this._queueAgain=this._queuePending;
    this._config = {...config}; this._key = ''; this._lyricKey = ''; this._queue = null;
    if (this._connected) { this._build(); this._render(); }
  }
  getCardSize() { return 8; }
  getGridOptions() { return {columns: 12, rows: 9, min_columns: 6, min_rows: 6}; }
  static getStubConfig(hass) { return {entity: Object.keys(hass.states).find(id => hass.states[id].attributes.feiniu_queue)}; }
  set hass(value) {
    this._hass = value;
    if (!this._connected || !this._config) return;
    this._render();
  }
  connectedCallback() {
    this._connected = true; document.addEventListener('visibilitychange', this._visibility);
    // HA masonry can detach/reinsert a card while its first request is pending.
    // The old epoch must be discarded, then replaced even if state keys did not change.
    this._key = ''; this._lyricKey = ''; this._queueAgain = this._queuePending;
    if (this._config) { this._build(); this._render(); }
  }
  disconnectedCallback() {
    this._connected = false; this._queueEpoch++; this._lyricEpoch++; this._browseEpoch++;
    this._stopAnimation(); document.removeEventListener('visibilitychange', this._visibility);
  }
  get _state() { return this._hass?.states[this._config?.entity]; }
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
    this._language=this._hass?.language || "en";
    // Only constant markup/CSS uses innerHTML. All library metadata and lyrics use textContent.
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;color:var(--primary-text-color,#182b35);font-size:14px;line-height:1.5;font-family:var(--primary-font-family,system-ui),sans-serif}
      *{box-sizing:border-box}ha-card{display:block;background:var(--ha-card-background,var(--card-background-color,#fff));border-radius:var(--ha-card-border-radius,16px);border:1px solid var(--divider-color,#dce2e6);overflow:hidden}
      header{padding:20px 20px 10px;display:flex;gap:12px;align-items:center}header div{min-width:0;flex:1}h2{margin:0;font-size:16px;font-weight:600;overflow-wrap:anywhere}.sub{color:var(--secondary-text-color,#5d707b);font-size:12px;overflow-wrap:anywhere}
      .now{display:grid;grid-template-columns:100px minmax(0,1fr);gap:18px;padding:12px 20px;align-items:center}.art{width:100px;height:100px;border-radius:10px;background:var(--secondary-background-color,#edf2f5);overflow:hidden;display:grid;place-items:center}.art img{height:100%;width:100%;object-fit:cover}.art feiniu-icon{--mdc-icon-size:44px;color:var(--secondary-text-color,#5d707b)}h3{font-size:22px;line-height:1.25;letter-spacing:-.4px;margin:0 0 7px;overflow-wrap:anywhere}.artist{overflow-wrap:anywhere}.album{font-size:12px;color:var(--secondary-text-color,#5d707b)}
      button,select,input{font:inherit;color:inherit}button{border:0;background:transparent;border-radius:9px;min-width:44px;min-height:44px;padding:8px;cursor:pointer}button:hover{background:var(--secondary-background-color,#edf2f5)}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--primary-color,#007ea0);outline-offset:2px}button:disabled{opacity:.35;cursor:default}button[aria-pressed=true]{color:var(--primary-color,#007ea0);background:var(--secondary-background-color,#edf2f5)}feiniu-icon{--mdc-icon-size:23px}#controls{display:flex;align-items:center;justify-content:center;gap:7px;padding:0 14px}#controls .main{width:58px;height:58px;border-radius:50%;background:var(--primary-color,#007ea0);color:var(--text-primary-color,#fff)}
      .progress{padding:12px 22px 0}.progress input{width:100%;margin:0;accent-color:var(--primary-color,#007ea0);height:28px}.times{display:flex;justify-content:space-between;font-variant-numeric:tabular-nums;font-size:12px;color:var(--secondary-text-color,#5d707b)}.volume{padding:6px 22px;display:flex;gap:12px;align-items:center;font-size:12px}.volume input{min-width:0;flex:1;accent-color:var(--primary-color,#007ea0)}
      #status{margin:8px 20px;padding-left:10px;border-left:3px solid var(--primary-color,#007ea0);font-size:13px;min-height:22px}#error{margin:6px 20px;color:var(--error-color,#b62c3d)}#error:empty{display:none}.tabs{display:flex;gap:6px;padding:12px 16px 4px;border-top:1px solid var(--divider-color,#dce2e6);margin-top:8px}.tabs button{flex:1;border-radius:6px 6px 0 0}.tabs button[aria-selected=true]{box-shadow:inset 0 -2px var(--primary-color,#007ea0);font-weight:650;color:var(--primary-color,#007ea0)}
      #content{min-height:200px;max-height:430px;overflow:auto;padding:8px 16px 16px}.row{display:flex;align-items:center;gap:4px;min-height:58px;border-bottom:1px solid var(--divider-color,#dce2e6)}.row.current{border-left:3px solid var(--primary-color,#007ea0);padding-left:5px}.row .name{flex:1;min-width:0;text-align:left;line-height:1.4;overflow-wrap:anywhere}.row small{display:block;color:var(--secondary-text-color,#5d707b);font-size:11px}.row .actions{display:flex;flex-shrink:0}.row .actions button{min-width:44px;width:44px;padding:4px}.row feiniu-icon{--mdc-icon-size:20px}.row img{width:38px;height:38px;object-fit:cover;border-radius:5px}.pager{display:flex;align-items:center;justify-content:space-between;padding-top:10px}.empty{padding:28px 8px;text-align:center;color:var(--secondary-text-color,#5d707b)}
      #lyric-lines{height:260px;overflow:auto;scrollbar-width:thin;padding:24px 12px;mask-image:linear-gradient(transparent,#000 12%,#000 88%,transparent)}#lyric-lines p{font-size:18px;line-height:1.65;margin:12px 0;color:var(--secondary-text-color,#5d707b);overflow-wrap:anywhere}#lyric-lines p.current{color:var(--primary-text-color,#182b35);font-weight:700}#lyric-lines pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}
      #browser{padding:0 16px 16px}#browser[hidden],#preferences[hidden]{display:none}.search{display:flex;gap:8px;padding:8px 0}.search input{min-width:0;flex:1;padding:8px;border:1px solid var(--divider-color,#dce2e6);border-radius:6px;background:transparent}.browse-heading{display:flex;align-items:center;gap:8px}.browse-heading strong{flex:1;min-width:0;overflow-wrap:anywhere}#browse-list{max-height:340px;overflow:auto}.footer{padding:0 20px 18px;font-size:11px;color:var(--secondary-text-color,#5d707b)}#preferences{border-top:1px solid var(--divider-color,#dce2e6);padding:16px 20px}#preferences label{display:block;margin:12px 0}#preferences select{max-width:100%;display:block;padding:8px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dce2e6);border-radius:5px}#preferences input[type=number]{width:90px;margin-left:10px;background:transparent;padding:6px;border:1px solid var(--divider-color,#dce2e6);border-radius:4px}#preferences input[type=checkbox]{margin-right:8px}pre.diagnostics{font-size:11px;overflow:auto;max-height:180px}summary{cursor:pointer;padding:8px 0}.muted{font-size:12px;color:var(--secondary-text-color,#5d707b)}
      @media(max-width:390px){header{padding:16px 16px 6px}.now{padding:10px 16px;grid-template-columns:80px minmax(0,1fr);gap:12px}.art{width:80px;height:80px}h3{font-size:19px}#controls{gap:2px;padding:0 8px}.row .actions button{min-width:44px;width:44px}.row img{display:none}#content{padding:8px 10px 12px}}
      @media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
    </style><ha-card><header><div><h2 id="heading"></h2><div class="sub" id="output"></div></div><span id="settings-button"></span></header>
    <div class="now"><div class="art"><feiniu-icon icon="mdi:music-note"></feiniu-icon><img id="art" hidden alt=""></div><div><h3 id="title"></h3><div id="artist" class="artist"></div><div id="album" class="album"></div></div></div>
    <div id="controls"></div><div class="progress"><input id="seek" type="range" min="0" max="100" step="1"><div class="times"><span id="elapsed">—</span><span id="duration">—</span></div></div>
    <label class="volume"><span id="volume-label"></span><input id="volume" type="range" min="0" max="1" step="0.01"></label><div id="status" role="status" aria-live="polite"></div><div id="error" role="alert"></div>
    <div class="tabs" role="tablist"></div><div id="content"></div><div id="browser" hidden><div class="browse-heading"><span id="browse-back"></span><strong id="browse-title"></strong><span id="browse-close"></span></div><form class="search"><input id="search"><button id="search-go" type="submit"></button></form><div id="browse-all"></div><div id="browse-list"></div></div>
    <div id="preferences" hidden><div id="preference-fields"></div><span id="save-preferences"></span><p id="warning" class="muted"></p><details><summary id="diagnostic-label"></summary><pre id="diagnostics" class="diagnostics"></pre></details></div><div id="footer" class="footer"></div></ha-card>`;
    this.$('settings-button').append(this._button('settings', () => this._preferences()));
    this._buttons = {};
    for (const key of ['shuffle','previous','play','next','stop','repeat']) {
      const button = this._button(key, () => this._transport(key)); button.id = `button-${key}`; if (key === 'play') button.className = 'main';
      this.$('controls').append(button); this._buttons[key] = button;
    }
    for (const key of ['queue','lyrics','browse']) {
      const b = this._button(key, () => {this._tab = key; this._renderContent(); if (key === 'browse') this._browse();}); b.setAttribute('role','tab'); b.dataset.tab = key; this.shadowRoot.querySelector('.tabs').append(b);
    }
    this.$('seek').setAttribute('aria-label', this.t('seek'));
    this.$('seek').oninput = () => { this._dragging = true; this._text('elapsed',timeLabel(Number(this.$('seek').value))); };
    this.$('seek').onchange = () => { this._dragging = false; this._service('media_seek',{seek_position:Number(this.$('seek').value)}); };
    this.$('volume').setAttribute('aria-label',this.t('volume')); this._text('volume-label',this.t('volume'));
    this.$('volume').onchange = () => this._service('volume_set',{volume_level:Number(this.$('volume').value)});
    this.$('art').onerror = () => {this.$('art').hidden=true; this.$('art').previousElementSibling.hidden=false;};
    this.$('browse-back').append(this._button('back', () => {this._browseStack.pop(); this._browse(this._browseStack.pop(),false);}));
    this.$('browse-close').append(this._button('close',()=>{this._tab='queue'; this._renderContent();}));
    this.$('search').placeholder=this.t('search'); this.$('search').setAttribute('aria-label',this.t('search')); this._text('search-go',this.t('searchGo'));
    this.shadowRoot.querySelector('form').onsubmit=e=>{e.preventDefault();this._browse(null,false,this.$('search').value.trim());};
    this._text('footer',this.t('footer')); this._text('warning',this.t('warning')); this._text('diagnostic-label',this.t('diagnostic'));
    this._renderContent();
  }
  _render() {
    if (!this.$('heading') || !this._hass) return;
    if(this._language!==(this._hass.language||'en'))this._build();
    const state=this._state,a=this._attrs;
    this._text('heading',this._config.title || a.friendly_name || 'FeiNiu Music');
    this._text('output',`${this.t('source')} · ${this._hass.states[a.output_player]?.attributes.friendly_name || a.output_player || '—'}`);
    this._text('title',a.media_title || this.t('unknown')); this._text('artist',a.media_artist); this._text('album',a.media_album_name);
    const image=safeImage(a.entity_picture || a.media_image_url);
    if(image && this.$('art').getAttribute('src')!==image){this.$('art').src=image;this.$('art').hidden=false;this.$('art').previousElementSibling.hidden=true;}
    if(!image){this.$('art').hidden=true;this.$('art').previousElementSibling.hidden=false;}
    const offline=!state || state.state==='unavailable';
    let message=offline ? this.t('offline') : this.t(a.session_reason in words.en ? a.session_reason : (a.session_phase || 'idle'));
    if(a.position_source==='estimated')message+=` · ${this.t('estimated')}`;
    this._text('status',message);
    const playing=state?.state==='playing', flags=a.supported_features || 0;
    this._buttons.play.firstChild.setAttribute('icon',`mdi:${playing?'pause':'play'}`);
    this._buttons.play.title=this.t(playing?'pause':'play');this._buttons.play.setAttribute('aria-label',this._buttons.play.title);
    for(const [key,b] of Object.entries(this._buttons)) b.disabled=offline || (key==='play' && playing && !(flags&1));
    this._buttons.stop.disabled=!(a.queue_length || a.session_phase==='loading');
    this._buttons.shuffle.setAttribute('aria-pressed',String(!!a.shuffle));this._buttons.repeat.setAttribute('aria-pressed',String(a.repeat!=='off'));
    this._buttons.repeat.title=`${this.t('repeat')} · ${a.repeat || 'off'}`;
    this.$('seek').disabled=offline || !(flags&2) || !a.queue_active || !a.media_duration;
    this.$('seek').max=String(a.media_duration || 100);this._text('duration',timeLabel(a.media_duration));
    this.$('volume').disabled=offline || !(flags&4);if(this.shadowRoot.activeElement!==this.$('volume'))this.$('volume').value=String(a.volume_level||0);
    const anchorKey=[a.media_position,a.media_position_updated_at,state?.state].join('|');
    if(anchorKey!==this._anchorKey){this._anchorKey=anchorKey;this._anchor={value:positionAt(a,state?.state,Date.now()),at:performance.now(),moving:playing};}
    const key=`${this._config.entity}/${a.queue_revision}`;
    if(key!==this._key){this._key=key;this._refreshQueue();}
    const lyricKey=`${this._config.entity}/${a.playback_round}/${a.queue_item_id}`;
    if(lyricKey!==this._lyricKey){this._lyricKey=lyricKey;this._refreshLyrics();}
    this._animate();
  }
  _position() {if(this._anchor?.value==null)return null;return Math.min(this._attrs.media_duration||Infinity,this._anchor.value+(this._anchor.moving?(performance.now()-this._anchor.at)/1000:0));}
  _stopAnimation(){if(this._raf)cancelAnimationFrame(this._raf);this._raf=0;}
  _animate(){
    this._stopAnimation();if(!this._connected||document.hidden)return;
    const tick=()=>{const p=this._position();if(!this._dragging){this.$('seek').value=String(p||0);this._text('elapsed',timeLabel(p));}
      if(this._tab==='lyrics'&&p!=null){const i=lyricIndex(this._lyrics,p,this._attrs.lyric_offset||0);if(i!==this._lastLine){this._lastLine=i;const lines=this.shadowRoot.querySelectorAll('#lyric-lines p');lines.forEach((line,index)=>line.classList.toggle('current',i===index));lines[i]?.scrollIntoView({block:'nearest',behavior:'auto'});}}
      if(this._state?.state==='playing'&&this._connected&&!document.hidden)this._raf=requestAnimationFrame(tick);};tick();
  }
  async _call(type,data={}){return this._hass.callWS({type,entity_id:this._config.entity,...data});}
  _error(err){this.$('error').style.color='var(--error-color,#b62c3d)';this.$('error').setAttribute('role','alert');this._text('error',err?.code==='revision_conflict'?this.t('conflict'):this.t('error'));if(err?.code==='revision_conflict')this._refreshQueue();}
  async _service(service,data={}){this._text('error','');try{await this._hass.callService('media_player',service,{entity_id:this._config.entity,...data});}catch(err){this._error(err);}}
  _transport(key){
    if(key==='shuffle')return this._service('shuffle_set',{shuffle:!this._attrs.shuffle});
    if(key==='repeat')return this._service('repeat_set',{repeat:{off:'one',one:'all',all:'off'}[this._attrs.repeat||'off']});
    return this._service({previous:'media_previous_track',next:'media_next_track',stop:'media_stop',play:this._state?.state==='playing'?'media_pause':'media_play'}[key]);
  }
  _refresh(){this._refreshQueue();this._refreshLyrics();}
  async _refreshQueue(){
    if(!this._hass||!this._connected||document.hidden)return;
    if(this._queuePending){this._queueAgain=true;return;}this._queuePending=true;const epoch=++this._queueEpoch;
    try{const page=await this._call('feiniu_music/queue',{offset:this._offset,limit:25});if(epoch!==this._queueEpoch||!this._connected)return;
      if(page.revision<this._attrs.queue_revision){this._queueAgain=true;return;}this._queue=page;this._text('diagnostics',JSON.stringify(page.diagnostics,null,2));this._renderContent();
    }catch(err){if(epoch===this._queueEpoch)this._error(err);}finally{this._queuePending=false;if(this._queueAgain){this._queueAgain=false;setTimeout(()=>this._refreshQueue(),150);}}
  }
  async _refreshLyrics(){
    if(!this._hass||!this._connected||document.hidden)return;const epoch=++this._lyricEpoch;
    this._lyrics=[];this._lyricText='';this._lyricStatus='loading';this._lastLine=-1;
    if(!this._attrs.queue_item_id){this._lyricStatus='noLyrics';this._renderContent();return;}
    const requested=this._lyricKey;
    try{const result=await this._call('feiniu_music/lyrics',{round:this._attrs.playback_round||0,item_id:this._attrs.queue_item_id});
      if(!this._connected||epoch!==this._lyricEpoch||requested!==this._lyricKey)return;
      this._lyrics=result.synced_lines||[];this._lyricText=result.text||'';this._lyricStatus=this._lyricText?'':'noLyrics';
    }catch(err){if(epoch!==this._lyricEpoch)return;this._lyricStatus=err?.code==='revision_conflict'?'loading':'lyricError';}
    this._renderContent();this._animate();
  }
  _empty(text){const p=document.createElement('div');p.className='empty';p.textContent=text;return p;}
  _renderContent(){
    const root=this.$('content');if(!root)return;root.replaceChildren();this.$('browser').hidden=this._tab!=='browse';root.hidden=this._tab==='browse';
    for(const b of this.shadowRoot.querySelectorAll('[role=tab]'))b.setAttribute('aria-selected',String(b.dataset.tab===this._tab));
    if(this._tab==='lyrics'){
      const box=document.createElement('div');box.id='lyric-lines';
      if(this._lyrics.length){for(const line of this._lyrics){const p=document.createElement('p');p.textContent=line.text;box.append(p);}}
      else if(this._lyricText){const p=document.createElement('pre');p.textContent=this._lyricText;box.append(p);}
      else box.append(this._empty(this.t(this._lyricStatus||'noLyrics')));root.append(box);this._lastLine=-1;return;
    }
    if(this._tab!=='queue')return;
    if(!this._queue){root.append(this._empty(this.t('loading')));return;}
    if(!this._queue.total){root.append(this._empty(this.t('empty')),this._button('browse',()=>{this._tab='browse';this._renderContent();this._browse();},this.t('browse')));return;}
    this._queue.items.forEach((item,index)=>{
      const row=document.createElement('div');row.className=`row${item.current?' current':''}`;
      const thumb=safeImage(item.thumbnail);if(thumb){const img=document.createElement('img');img.src=thumb;img.alt='';img.loading='lazy';row.append(img);}
      const name=this._button('jump',()=>this._edit('jump',item.item_id));name.className='name';name.textContent=item.title;name.setAttribute('aria-label',`${this.t('jump')} · ${item.title}`);
      const sub=document.createElement('small');sub.textContent=`${this._offset+index+1} · ${item.artist||''}`;name.append(sub);row.append(name);
      const actions=document.createElement('div');actions.className='actions';
      const absolute=this._offset+index,pending=absolute>this._queue.position;
      const up=this._button('up',()=>this._edit('move',item.item_id,this._queue.items[index-1].item_id));up.disabled=!pending||index===0||absolute<=this._queue.position+1;
      const down=this._button('down',()=>this._edit('move',item.item_id,this._queue.items[index+2]?.item_id||null));down.disabled=!pending||index>=this._queue.items.length-1;
      actions.append(up,down,this._button('remove',()=>this._edit('remove',item.item_id)));row.append(actions);root.append(row);
    });
    const pager=document.createElement('div');pager.className='pager';const back=this._button('back',()=>{this._offset=Math.max(0,this._offset-25);this._refreshQueue();});back.disabled=this._offset===0;
    const count=document.createElement('span');count.textContent=`${this._queue.total} ${this.t('count')}`;
    const next=this._button('more',()=>{this._offset+=25;this._refreshQueue();});next.disabled=this._offset+25>=this._queue.total;
    pager.append(back,count,next,this._button('clear',()=>this._edit('clear')));root.append(pager);
  }
  async _edit(action,itemId,beforeId){if(!this._queue)return;this._text('error','');try{await this._call('feiniu_music/edit_queue',{action,revision:this._queue.revision,...(itemId?{item_id:itemId}:{}),...(beforeId!==undefined?{before_id:beforeId}:{})});this._refreshQueue();}catch(err){this._error(err);}}
  async _browse(item=null,push=true,query=''){
    if(!this._hass)return;const epoch=++this._browseEpoch;this.$('browse-list').replaceChildren(this._empty(this.t('loading')));
    try{const data=item?{media_content_id:item.media_content_id,media_content_type:item.media_content_type}:{};
      let result=await this._call(query?'media_player/search_media':'media_player/browse_media',{...data,...(query?{media_search_query:query}:{})});
      if(epoch!==this._browseEpoch||!this._connected)return;
      if(query)result={title:query,children:result.result||[]};
      if(push)this._browseStack.push(item);this._text('browse-title',result.title||this.t('browse'));this.$('browse-all').replaceChildren();
      if(result.can_play)this.$('browse-all').append(this._button('play',()=>this._select(result,'replace'),this.t('browseAll')),this._button('add',()=>this._select(result,'add')));
      const list=this.$('browse-list');list.replaceChildren();
      for(const child of result.children||[]){const row=document.createElement('div');row.className='row';
        const name=this._button(child.can_expand?'browse':'play',()=>child.can_expand?this._browse(child):this._select(child,'replace'));name.className='name';name.textContent=child.title;name.setAttribute('aria-label',child.title);row.append(name);
        if(child.can_play)row.append(this._button('add',()=>this._select(child,'add')),this._button('playnext',()=>this._select(child,'next')));list.append(row);}
      if(!list.childElementCount)list.append(this._empty(this.t('emptyQueue')));
    }catch(err){if(epoch===this._browseEpoch){this.$('browse-list').replaceChildren(this._empty(this.t('error')));this._error(err);}}
  }
  async _select(item,enqueue){await this._service('play_media',{media_content_type:item.media_content_type,media_content_id:item.media_content_id,enqueue});this._refreshQueue();}
  _preferences(){
    const box=this.$('preferences');box.hidden=!box.hidden;if(box.hidden)return;
    const fields=this.$('preference-fields');fields.replaceChildren();const profile=this._queue?.diagnostics?.profile||{confirmation:'delivery',play_once:false,end_state:'idle',weak_end:false};
    const label=(key,input)=>{const l=document.createElement('label');l.textContent=this.t(key);l.append(input);fields.append(l);};
    const offset=document.createElement('input');offset.type='number';offset.min='-30';offset.max='30';offset.step='.1';offset.id='offset';offset.value=String(this._attrs.lyric_offset||0);label('offset',offset);
    const select=(key,id,choices,value)=>{const input=document.createElement('select');input.id=id;for(const [v,t]of choices){const o=document.createElement('option');o.value=v;o.textContent=t;input.append(o);}input.value=value;label(key,input);};
    select('confirmation','confirmation',[['delivery',this.t('delivery')],['reported',this.t('reported')]],profile.confirmation);
    select('end','end-state',[['idle','IDLE'],['paused','PAUSED'],['off','OFF']],profile.end_state);
    for(const [key,id,value] of [['playOnce','play-once',profile.play_once],['weak','weak-end',profile.weak_end]]){const input=document.createElement('input');input.type='checkbox';input.id=id;input.checked=value;label(key,input);}
    for(const id of ['confirmation','end-state','play-once','weak-end'])this.$(id).disabled=!this._hass.user?.is_admin;
    this.$('save-preferences').replaceChildren(this._button('save',async()=>{try{
      await this._call('feiniu_music/preferences',{lyric_offset:Number(this.$('offset').value),...(this._hass.user?.is_admin?{profile:{confirmation:this.$('confirmation').value,play_once:this.$('play-once').checked,end_state:this.$('end-state').value,weak_end:this.$('weak-end').checked}}:{})});
      this.$('error').style.color='var(--secondary-text-color,#5d707b)';this.$('error').setAttribute('role','status');this._text('error',this.t('saved'));box.hidden=true;this._refreshQueue();}catch(err){this._error(err);}}));
  }
}
if(globalThis.customElements&&!customElements.get('feiniu-music-card')){
  customElements.define('feiniu-music-card',FeiNiuMusicCard);
  window.customCards=window.customCards||[];window.customCards.push({type:'feiniu-music-card',name:'FeiNiu Music',description:'Fixed-output queue and lyrics',preview:true});
}
