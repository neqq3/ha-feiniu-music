// HA's native form controls edit appearance only; no service calls or player settings.
export class FeiNiuCardEditor extends (globalThis.HTMLElement || class {}) {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this._config={...config};this._render();}
  set hass(value){this._hass=value;this._render();}
  connectedCallback(){this._render();}
  _render(){
    if(!this._config||!this._hass)return;
    const zh=this._hass.language?.startsWith('zh');
    const labels=zh?{entity:'飞牛播放器',display_mode:'展示模式',compact_view:'紧凑卡片内容',compact_background:'紧凑卡片背景',compact_mask:'蒙版效果',title:'标题',theme:'配色',height:'完整界面高度（像素）'}:{entity:'FeiNiu player',display_mode:'Display mode',compact_view:'Compact content',compact_background:'Compact background',compact_mask:'Overlay effect',title:'Title',theme:'Colors',height:'Full interface height (pixels)'};
    if(!this._form){
      this.shadowRoot.innerHTML='<style>:host{display:block}.hint{color:var(--secondary-text-color);font-size:13px;line-height:1.6;margin:16px 0}</style><ha-form></ha-form><p class="hint"></p>';
      this._form=this.shadowRoot.querySelector('ha-form');
      this._form.addEventListener('value-changed',event=>{
        event.stopPropagation();const next={...this._config,...event.detail.value};
        for(const key of ['title','height'])if(next[key]===''||next[key]==null)delete next[key];
        if(JSON.stringify(next)===JSON.stringify(this._config))return;
        this._config=next;this._render();
        this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:{...next}},bubbles:true,composed:true}));
      });
    }
    const entities=Object.keys(this._hass.states).filter(id=>id.startsWith('media_player.')&&this._hass.states[id].attributes.feiniu_queue);
    // Retain a configured player even if it is temporarily absent/offline.
    if(this._config.entity&&!entities.includes(this._config.entity))entities.push(this._config.entity);
    const mode=this._config.display_mode||'full',artwork=this._config.compact_background==='artwork',key=JSON.stringify([zh,mode,artwork,entities]);
    if(this._schemaKey!==key){
      this._schemaKey=key;
      this._form.schema=[
        {name:'entity',required:true,selector:{entity:{filter:{domain:'media_player'},include_entities:entities}}},
        {name:'display_mode',required:true,selector:{select:{mode:'dropdown',options:[
          {value:'compact',label:zh?'紧凑卡片 · 普通仪表盘':'Compact card · dashboard'},
          {value:'full',label:zh?'完整界面 · 音乐页面':'Full interface · music page'},
        ]}}},
        ...(mode==='compact'?[{name:'compact_view',selector:{select:{mode:'dropdown',options:[
          {value:'simple',label:zh?'精简播放器':'Simple player'},
          {value:'lyrics',label:zh?'歌词播放器':'Lyrics player'},
          {value:'auto',label:zh?'自动 · 有歌词显示，无歌词精简':'Auto · lyrics when available, simple otherwise'},
        ]}}},{name:'compact_background',selector:{select:{mode:'dropdown',options:[
          {value:'default',label:zh?'原默认背景与透明度':'Original background and opacity'},
          {value:'artwork',label:zh?'封面氛围':'Artwork colors'},
        ]}}}]:[]),
        ...(mode==='compact'&&artwork?[{name:'compact_mask',selector:{select:{mode:'dropdown',options:[
          {value:'soft',label:zh?'柔和蒙版 · 默认':'Soft overlay · default'},
          {value:'glass',label:zh?'通透玻璃':'Translucent glass'},
        ]}}}]:[]),
        {name:'title',selector:{text:{}}},
        {name:'theme',selector:{select:{mode:'dropdown',options:[
          {value:'auto',label:zh?'跟随 Home Assistant':'Follow Home Assistant'},
          {value:'dark',label:zh?'深色':'Dark'},{value:'light',label:zh?'浅色':'Light'},
        ]}}},
        ...(mode==='full'?[{name:'height',selector:{number:{min:600,max:1200,step:1,mode:'box'}}}]:[]),
      ];
      this._form.computeLabel=schema=>labels[schema.name]||schema.name;
      this._form.computeHelper=schema=>schema.name==='height'?(zh?'留空时使用页面可用高度。':'Leave empty to use the available page height.'):undefined;
    }
    this._form.hass=this._hass;
    const data={...this._config,display_mode:mode,compact_view:this._config.compact_view||'simple',compact_background:this._config.compact_background||'default',compact_mask:this._config.compact_mask||'soft',theme:this._config.theme||'dark'};
    if(JSON.stringify(data)!==this._dataKey){this._dataKey=JSON.stringify(data);this._form.data=data;}
    this.shadowRoot.querySelector('.hint').textContent=zh
      ?'自动模式有歌词时显示歌词播放器，没有歌词时恢复精简卡片；歌词模式无歌词时显示提示。点封面或展开按钮打开完整界面。起播与续播设置请到集成配置中调整。'
      :'Auto shows a lyrics player when lyrics exist and a simple card otherwise. Lyrics mode shows a message when none exist. Open the artwork or expand button for the full interface. Playback compatibility is configured in the integration.';
  }
}
if(globalThis.customElements&&!customElements.get('feiniu-music-card-editor'))customElements.define('feiniu-music-card-editor',FeiNiuCardEditor);
