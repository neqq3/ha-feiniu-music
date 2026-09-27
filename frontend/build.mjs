import {copyFile, mkdir} from 'node:fs/promises';
await mkdir('custom_components/feiniu_music/www', {recursive:true});
await copyFile('frontend/feiniu-music-card.js','custom_components/feiniu_music/www/feiniu-music-card.js');
console.log('Built standalone card; no runtime imports or CDN dependencies.');
