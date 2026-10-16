// Optional third argument: a Step event decompiled from the real patched game.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const {fixture,extract}=require('./test_playback_controls.cjs');
const stock=process.argv[3]?fs.readFileSync(process.argv[3],'utf8'):null;
let checks=0,failures=0;
function test(name,fn){checks++;try{fn();console.log('PASS '+name);}catch(e){failures++;console.log('FAIL '+name+': '+e.message);}}
function player(mode=2){
  const c=fixture(['ne:A','qq:B','ne:C'],0,mode);
  Object.assign(c,{
    qqm_online_active:1,qqm_play_generation:0,qqm_req_play_generation:0,
    qqm_source:'ne',qqm_req_source:'ne',qqm_req_life:0,qqm_kind:'',
    qqm_ready:1,qqm_loading:0,qqm_lists_pending:0,qqm_dead:[],
    qqm_base:'http://127.0.0.1:38612',nextId:100,requests:[],
    music_list:[10,11,12],music_names:['local-A','local-B','local-C'],
    current_music_index:0,current_random_music:0,random_music_list:[0,1,2],
    no_window:()=>false,page_music_list:-1,
    string_copy:(s,p,n)=>s.slice(p-1,p-1+n),qqm_urlenc:encodeURIComponent,
    ds_map_find_value:(o,k)=>o[k],is_struct:o=>!!o&&typeof o==='object',
    json_parse:JSON.parse,variable_struct_exists:(o,k)=>Object.hasOwn(o,k),
  });
  c.http_get=url=>{const id=c.nextId++;c.requests.push({id,url});return id;};
  vm.runInContext(['qqm_get','qqm_try_send_play','qqm_play_from_queue','qqm_fail_play','qqm_async_body','qqm_bar_title'].map(extract).join('\n'),c);
  return c;
}
function reply(c,payload,id=c.qqm_req,status=0){c.qqm_async_body({id,status,result:JSON.stringify(payload)});}
function stockStep(c){
  assert(stock,'real Step event required');
  const start=stock.indexOf('var mx_gui = device_mouse_x_to_gui(0);'),end=stock.indexOf('var lay_id = layer_get_id(');
  assert(start>=0&&end>start,'stock player event located');
  vm.runInContext(stock.slice(start,end),c);
}
function hasLocalPlay(c){return c.calls.some(call=>call[0]==='play'&&c.music_list.includes(call[1]));}

test('selecting online music silences the cassette before loading',()=>{
  const c=player();c.playing.add(10);c.qqm_online_active=0;c.qqm_play_from_queue(1);
  assert(!c.playing.has(10));assert.equal(c.qqm_online_active,1);assert.equal(c.qqm_play_state,'preparing');
});
test('an unavailable queued song leaves the online player in charge',()=>{
  const c=player();c.qqm_online_active=0;c.qqm_play_from_queue(1);c.qqm_fail_play('trial only');
  assert.equal(c.qqm_online_active,1);assert.equal(c.qqm_status,'trial only');
});
test('an explicit stop releases online ownership',()=>{
  const c=player();c.qqm_stop();assert.equal(c.qqm_online_active,0);
});
test('failed playback retains the queue position for the next command',()=>{
  const c=player(0);c.qqm_play_from_queue(1);c.qqm_fail_play('not available');
  assert.equal(c.qqm_play_index,1);c.qqm_shift(1);assert.equal(c.qqm_play_id,'ne:C');
});
test('failed playback keeps the queue song title rather than a local cassette title',()=>{
  const c=player();c.qqm_play_from_queue(1);c.qqm_fail_play('not available');
  assert.equal(c.qqm_bar_title(),'qq:B');assert.equal(c.qqm_play_id,'qq:B');
});
test('late ready response cannot play an older selection',()=>{
  const c=player();c.qqm_play_from_queue(0);const old=c.qqm_req;
  c.qqm_play_from_queue(1);c.calls.length=0;
  reply(c,{ok:true,state:'ready',file:'cache/old-A.ogg'},old);
  assert(!c.calls.some(v=>v[0]==='create'));assert.equal(c.qqm_play_id,'qq:B');
  assert.match(c.requests.at(-1).url,/\/play\?id=qq%3AB/);
});
test('late failure cannot erase the newly selected queued song',()=>{
  const c=player();c.qqm_play_from_queue(0);const old=c.qqm_req;c.qqm_play_from_queue(1);
  reply(c,{ok:false,state:'error',msg:'old failure'},old);
  assert.equal(c.qqm_play_id,'qq:B');assert.notEqual(c.qqm_status,'old failure');
});
test('late transport error cannot mark a newer selection offline',()=>{
  const c=player();c.qqm_play_from_queue(0);const old=c.qqm_req;c.qqm_play_from_queue(1);
  reply(c,{},old,-1);assert.equal(c.qqm_ready,1);assert.equal(c.qqm_play_id,'qq:B');
});
test('A to B to A still rejects the reply belonging to the first selection',()=>{
  const c=player();c.qqm_play_from_queue(0);const old=c.qqm_req;
  c.qqm_play_from_queue(1);c.qqm_play_from_queue(0);c.calls.length=0;
  reply(c,{ok:true,state:'ready',file:'cache/first-A.ogg'},old);
  assert(!c.calls.some(v=>v[0]==='create'));assert.equal(c.requests.length,2);
});
test('an obsolete poll cannot restart online music after local takeover',()=>{
  const c=player();c.qqm_get('/playstate?id=ne%3AA','poll');const old=c.qqm_req;c.qqm_stop();c.calls.length=0;
  reply(c,{ok:true,state:'ready',file:'cache/old-A.ogg'},old);
  assert(!c.calls.some(v=>v[0]==='create'));assert.equal(c.qqm_online_active,0);
});
test('the current reply still starts its matching song',()=>{
  const c=player();c.qqm_play_from_queue(1);
  reply(c,{ok:true,state:'ready',file:'cache/current-B.ogg'});
  assert(c.calls.some(v=>v[0]==='create'&&v[1].endsWith('current-B.ogg')));
  assert.equal(c.qqm_play_id,'qq:B');assert.equal(c.qqm_online_active,1);
});
test('explicitly starting the same local cassette relinquishes online control',()=>{
  const c=player();c.playing.add(c.current_music);c.qqm_step_body();
  assert.equal(c.qqm_online_active,0);assert.equal(c.qqm_sound,-1);
});

if(stock){
  for(const mode of [0,1,2])for(const phase of ['preparing','requesting','error'])
  test('stock player cannot leak a cassette in mode '+mode+' while '+phase,()=>{
    const c=player(mode);
    if(phase==='requesting'){c.qqm_req=88;c.qqm_kind='prefetch';}
    c.qqm_play_from_queue(1);
    if(phase==='error')c.qqm_fail_play('not available');
    c.calls.length=0;stockStep(c);assert(!hasLocalPlay(c));
  });
  for(const mode of [0,1,2])test('next during buffering has no stock-player side effect in mode '+mode,()=>{
    const c=player(mode);c.qqm_play_from_queue(1);c.calls.length=0;
    c.device_mouse_x_to_gui=()=>450;c.device_mouse_y_to_gui=()=>680;c.mouse_check_button_pressed=()=>true;
    stockStep(c);assert(!hasLocalPlay(c));
    c.qqm_step_body();assert(c.qqm_queue.some(t=>t.id===c.qqm_play_id));
  });
  test('local player remains available after online playback is stopped',()=>{
    const c=player();c.qqm_stop();c.calls.length=0;stockStep(c);assert(hasLocalPlay(c));
  });
  test('unlocking a scene does not start a cassette outside the online queue',()=>{
    const c=player();Object.assign(c,{first_time_new_scene:[0,0],current_scene:1,album_list:[[],[13]],album_name_list:[[],['new-scene']],array_contains:(a,v)=>a.includes(v)});
    const end=stock.indexOf('if (current_scene == 6)');assert(end>0);
    vm.runInContext(stock.slice(0,end),c);assert(!hasLocalPlay(c));
  });
}
console.log(checks+' queue-isolation checks, '+failures+' failures'+(stock?' (including real stock event)':''));
if(failures)process.exitCode=1;
