import test from 'node:test';
import assert from 'node:assert/strict';
import {timeLabel, lyricIndex, positionAt, safeImage} from './feiniu-music-card.js';

test('time labels reject invalid values and retain hours',()=>{
 assert.equal(timeLabel(NaN),'—');assert.equal(timeLabel(-1),'—');assert.equal(timeLabel(null),'—');
 assert.equal(timeLabel(3601.9),'60:01');
});
test('lyric selection follows backward seek, duplicates and visual offset',()=>{
 const lines=[{time_ms:1000},{time_ms:1000},{time_ms:4000},{time_ms:8000}];
 assert.equal(lyricIndex(lines,.5),-1);assert.equal(lyricIndex(lines,1),1);
 assert.equal(lyricIndex(lines,8),3);assert.equal(lyricIndex(lines,2),1);
 assert.equal(lyricIndex(lines,2,2),2);assert.equal(lyricIndex([],4),-1);
});
test('standard HA anchors extrapolate only playing state and clamp duration',()=>{
 const a={media_position:10,media_position_updated_at:'2026-01-01T00:00:00Z',media_duration:40};
 const now=Date.parse(a.media_position_updated_at)+15000;
 assert.equal(positionAt(a,'playing',now),25);assert.equal(positionAt(a,'paused',now),10);
 assert.equal(positionAt(a,'playing',now+60000),40);assert.equal(positionAt({},'playing',now),null);
});
test('artwork never accepts script/data/protocol-relative URLs',()=>{
 for(const value of ['javascript:alert(1)','data:text/html,test','//evil.invalid/a',null])assert.equal(safeImage(value),null);
 assert.equal(safeImage('/api/media_player_proxy/player'),'/api/media_player_proxy/player');
 assert.equal(safeImage('https://ha.invalid/a'),'https://ha.invalid/a');
});
