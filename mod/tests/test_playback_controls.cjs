// Run the actual GML control logic with distinct stream-resource and voice IDs.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),path=require('path');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'..','gml_Script_qqm_mod.gml'),'utf8');
function extract(name) {
  let match=source.match(new RegExp('^function '+name+'\\([^]*?^}', 'm'));
  if(!match) {
    match=source.match(new RegExp('^'+name+' = function\\([^]*?^};','m'));
    assert(match,name);
    return match[0].replace(name+' = function','function '+name).replace(/\bexit;/g,'return;').slice(0,-1)
      .replace(/qqm_prep_frames div 60/g,'Math.floor(qqm_prep_frames / 60)');
  }
  return match[0].replace(/qqm_prep_frames div 60/g,'Math.floor(qqm_prep_frames / 60)');
}
function fixture(ids=['A','B','C','D'],current=1,mode=0) {
  const calls=[],playing=new Set([9001]),c={calls,playing,
    qqm_sound:7001,qqm_voice:9001,qqm_saved_music:10,current_music:10,
    qqm_online_active:1,qqm_play_generation:0,qqm_req_play_generation:0,
    qqm_play_index:current,qqm_play_id:ids[current]||'',qqm_play_file:'cache/current.ogg',
    qqm_play_title:'current',qqm_play_singer:'artist',qqm_play_state:'playing',
    qqm_play_frames:0,qqm_playing:1,music_playing:1,slider_x:100,music_mode:mode,
    qqm_last_mode:mode,qqm_shuffle_ids:[],qqm_shuffle_order:[],qqm_shuffle_pos:-1,
    qqm_queue:ids.map(id=>({id,name:id,singer:''})),qqm_pending_play:-1,
    qqm_demo:0,qqm_hud_timer:-1,qqm_toast_time:0,qqm_req:-1,qqm_clicks:0,
    qqm_open:0,qqm_view:0,qqm_search_focus:0,
    qqm_prefetch_cd:0,qqm_prefetch_q:0,qqm_hover_prefetch:0,qqm_hovered:-1,
    qqm_hover_frames:0,qqm_prefetch_ahead:0,qqm_pf_next:999,qqm_pf_waiting:0,
    qqm_pf_target:'',qqm_prep_frames:0,page_customization:0,
    working_directory:'C:/game/',global:{qqm_stream:7001,qqm_voice:9001},
    mb_left:0,mouse_check_button_pressed:()=>false,
    device_mouse_x_to_gui:()=>0,device_mouse_y_to_gui:()=>0,
    string:String,string_pos:(s,t)=>t.indexOf(s)+1,
    array_length:a=>a.length,array_push:(a,x)=>a.push(x),
    array_shuffle:a=>a.slice().reverse(),max:Math.max,min:Math.min,clamp:(v,a,b)=>Math.min(b,Math.max(a,v)),
    qqm_try_load_lists:()=>{},qqm_try_send_play:()=>{},qqm_get:()=>{},qqm_text:k=>k,
    file_exists:()=>true,variable_global_exists:k=>Object.hasOwn(c.global,k),
  };
  c.audio_stop_sound=id=>{calls.push(['stop',id]);playing.delete(id);};
  c.audio_destroy_stream=id=>calls.push(['destroy',id]);
  c.audio_create_stream=file=>{calls.push(['create',file]);return c.createResult??7002;};
  c.audio_play_sound=(id,priority,loop,gain)=>{
    calls.push(['play',id,priority,loop,gain]);
    const voice=c.playResult??9002;if(voice!==-1)playing.add(voice);return voice;
  };
  c.audio_sound_gain=(id,gain,time)=>calls.push(['gain',id,gain,time]);
  c.audio_pause_sound=id=>{calls.push(['pause',id]);playing.delete(id);};
  c.audio_resume_sound=id=>{calls.push(['resume',id]);playing.add(id);};
  c.audio_is_playing=id=>playing.has(id);
  c.qqm_play_from_queue=i=>{
    assert(i>=0&&i<c.qqm_queue.length,'valid queue index');
    c.qqm_play_index=i;c.qqm_play_id=c.qqm_queue[i].id;calls.push(['select',i]);
  };
  c.qqm_fail_play=msg=>{c.failed=msg;c.qqm_play_state='';};
  vm.createContext(c);
  vm.runInContext(['qqm_sync_mode','qqm_shift','qqm_step_body','qqm_start_stream','qqm_stop'].map(extract).join('\n'),c);
  return c;
}
module.exports = {fixture, extract};
if (require.main === module) {
let count=0;
function test(name,fn){fn();count++;console.log('PASS '+name);}
for(const [slider,gain]of [[0,0],[25,.25],[50,.5],[100,1],[-5,0],[150,1]])
test('volume '+slider+' applies to the active voice',()=>{
  const c=fixture();c.slider_x=slider;c.qqm_step_body();
  assert.deepEqual(c.calls.find(v=>v[0]==='gain'),['gain',9001,gain,0]);
});
test('new songs start at the selected volume without a loud first frame',()=>{
  const c=fixture();c.slider_x=25;c.qqm_start_stream('cache/next.ogg');
  assert.deepEqual(c.calls.find(v=>v[0]==='play'),['play',7002,99,false,.25]);
  assert.equal(c.qqm_voice,9002);assert.equal(c.global.qqm_voice,9002);
  assert.equal(c.global.qqm_stream,7002);
  assert(c.calls.some(v=>v[0]==='stop'&&v[1]===9001));
  assert(c.calls.some(v=>v[0]==='destroy'&&v[1]===7001));
});
test('gain on the next frame follows the replacement voice',()=>{
  const c=fixture();c.qqm_start_stream('cache/next.ogg');c.slider_x=0;c.calls.length=0;c.qqm_step_body();
  assert.deepEqual(c.calls.find(v=>v[0]==='gain'),['gain',9002,0,0]);
});
test('paused music keeps its place and can change volume',()=>{
  const c=fixture();c.music_playing=-1;c.qqm_step_body();
  assert(c.calls.some(v=>v[0]==='pause'&&v[1]===9001));
  c.slider_x=20;c.qqm_step_body();assert.equal(c.qqm_play_index,1);
  assert(c.calls.some(v=>v[0]==='gain'&&v[2]===.2));
  c.music_playing=1;c.qqm_step_body();
  assert(c.calls.some(v=>v[0]==='resume'&&v[1]===9001));
});
test('stop releases the voice and resource and clears shared handles',()=>{
  const c=fixture();c.qqm_stop();
  assert.deepEqual(c.calls.slice(0,2),[['stop',9001],['destroy',7001]]);
  assert.equal(c.qqm_sound,-1);assert.equal(c.qqm_voice,-1);
  assert.equal(c.global.qqm_voice,-1);assert.equal(c.global.qqm_stream,-1);
});
test('a failed voice allocation does not create an endless completion loop',()=>{
  const c=fixture();c.playResult=-1;c.qqm_start_stream('cache/next.ogg');
  assert.equal(c.failed,'noaudio');assert.equal(c.qqm_sound,-1);assert.equal(c.global.qqm_stream,-1);
});
test('a failed stream allocation clears the previous shared handles',()=>{
  const c=fixture();c.createResult=-1;c.qqm_start_stream('cache/next.ogg');
  assert.equal(c.qqm_sound,-1);assert.equal(c.qqm_voice,-1);
  assert.equal(c.global.qqm_stream,-1);assert.equal(c.global.qqm_voice,-1);
});
test('list loop wraps naturally from last song to first',()=>{
  const c=fixture(['A','B','C'],2);c.playing.clear();c.qqm_step_body();
  assert.equal(c.qqm_play_index,0);assert.equal(c.qqm_play_id,'A');
});
test('previous wraps from first song to last',()=>{
  const c=fixture(['A','B','C'],0);c.qqm_shift(-1);assert.equal(c.qqm_play_index,2);
});
test('single repeat restarts the current cached song on completion',()=>{
  const c=fixture(['A','B','C'],1,1);c.playing.clear();c.qqm_step_body();
  assert.equal(c.qqm_play_index,1);assert.equal(c.qqm_play_id,'B');
  assert(c.calls.some(v=>v[0]==='create'&&v[1].endsWith('cache/current.ogg')));
  assert(!c.calls.some(v=>v[0]==='select'));
});
for(const direction of [-1,1])test('single repeat permits manual skip '+direction,()=>{
  const c=fixture(['A','B','C'],1,1);c.qqm_shift(direction);
  assert.equal(c.qqm_play_index,1+direction);
});
for(const mode of [0,1,2])test('one queued song loops in mode '+mode,()=>{
  const c=fixture(['A'],0,mode);c.playing.clear();c.qqm_step_body();
  assert.equal(c.qqm_play_index,0);assert.equal(c.qqm_play_frames,30);
  assert(c.calls.some(v=>v[0]==='play'));
});
test('empty queue does not select a nonexistent song',()=>{
  const c=fixture([], -1,2);c.qqm_shift(1,true);assert.equal(c.calls.length,0);
});
test('a removed active song advances to the first remaining item',()=>{
  const c=fixture(['A','B','C'],-1,0);c.qqm_shift(1,true);assert.equal(c.qqm_play_index,0);
});
test('shuffle visits every queued song before reshuffling',()=>{
  const c=fixture(['A','B','C','D'],1,2),visited=[c.qqm_play_id];
  for(let n=0;n<3;n++){c.qqm_shift(1,true);visited.push(c.qqm_play_id);}
  assert.equal(new Set(visited).size,4);
  assert.notDeepEqual(visited,['B','C','D','A']);
});
test('shuffle does not repeat at a round boundary and covers the new round',()=>{
  const c=fixture(['A','B','C','D'],1,2);
  for(let n=0;n<3;n++)c.qqm_shift(1,true);
  const previous=c.qqm_play_id,round=[];
  for(let n=0;n<4;n++){c.qqm_shift(1,true);round.push(c.qqm_play_id);}
  assert.notEqual(round[0],previous);assert.equal(new Set(round).size,4);
});
test('shuffle previous retraces the current shuffled order',()=>{
  const c=fixture(['A','B','C','D'],1,2);c.qqm_shift(1);const previous=c.qqm_play_id;
  c.qqm_shift(1);const next=c.qqm_play_id;c.qqm_shift(-1);assert.equal(c.qqm_play_id,previous);
  c.qqm_shift(1);assert.equal(c.qqm_play_id,next);
});
for(const operation of ['remove','insert','reorder','replace'])test('shuffle remains valid after queue '+operation,()=>{
  const c=fixture(['A','B','C','D'],1,2);c.qqm_shift(1);
  const active=c.qqm_play_id;
  if(operation==='remove')c.qqm_queue=c.qqm_queue.filter(t=>t.id!== 'A');
  if(operation==='insert')c.qqm_queue.splice(1,0,{id:'X'});
  if(operation==='reorder')c.qqm_queue.reverse();
  if(operation==='replace')c.qqm_queue=[{id:active},{id:'X'},{id:'Y'}];
  c.qqm_play_index=c.qqm_queue.findIndex(t=>t.id===active);c.qqm_shift(1);
  assert.notEqual(c.qqm_play_id,active);
  assert.equal(c.qqm_queue[c.qqm_play_index].id,c.qqm_play_id);
});
test('switching from shuffle to repeat-one takes effect on natural completion',()=>{
  const c=fixture(['A','B','C','D'],1,2);c.qqm_shift(1);const current=c.qqm_play_id;
  c.music_mode=1;c.playing.clear();c.qqm_step_body();assert.equal(c.qqm_play_id,current);
  assert.equal(c.qqm_shuffle_order.length,0);
});
test('shuffle handles selecting a different song directly',()=>{
  const c=fixture(['A','B','C','D'],1,2);c.qqm_shift(1);
  c.qqm_play_index=0;c.qqm_play_id='A';c.qqm_shift(1);
  assert.notEqual(c.qqm_play_id,'A');assert.equal(c.qqm_shuffle_ids.length,4);
});
console.log(count+' playback-control checks passed');
}
