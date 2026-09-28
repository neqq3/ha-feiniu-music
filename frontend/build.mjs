import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {CARD_CSS} from './card-styles.js';
import {CARD_ICONS} from './card-icons.js';
import {CARD_FONT} from './card-font.js';
import {CARD_BRAND} from './card-brand.js';
import {COMPACT_CSS} from './card-compact.js';
let bundle=await readFile('frontend/feiniu-music-card.js','utf8');
for(const [name,file,value]of [['CARD_CSS','card-styles',CARD_CSS],['CARD_ICONS','card-icons',CARD_ICONS],['CARD_FONT','card-font',CARD_FONT],['CARD_BRAND','card-brand',CARD_BRAND],['COMPACT_CSS','card-compact',COMPACT_CSS]]){
  bundle=bundle.replace(`import {${name}} from './${file}.js';`,`const ${name} = ${JSON.stringify(value)};`);
}
bundle=bundle.replace("import './card-editor.js';",(await readFile('frontend/card-editor.js','utf8')).replace('export class','class'));
// Preserve the embedded font's license in the distributed single-file resource.
const license=(await readFile('frontend/Montserrat-OFL.txt','utf8')).replace(/[ \t]+$/gm,'');
bundle=`/* Montserrat — SIL OFL 1.1\n${license}\n*/\n/* Hand-authored UI icons; user-reference brand redraw. See frontend/REFERENCE_ASSETS.md. */\n`+bundle;
await mkdir('custom_components/feiniu_music/www', {recursive:true});
await writeFile('custom_components/feiniu_music/www/feiniu-music-card.js',bundle);
console.log('Built card with hand-authored UI icons (including OFL font license).');
