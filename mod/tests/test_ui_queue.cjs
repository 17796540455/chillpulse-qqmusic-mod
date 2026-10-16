// Execute the C-style GML queue and draw logic with stubbed game APIs.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, '..', 'gml_Script_qqm_mod.gml'), 'utf8');
function extract(name) {
  let match = source.match(new RegExp('^function ' + name + '\\([^]*?^}', 'm'));
  if (!match) {
    match = source.match(new RegExp('^' + name + ' = function\\([^]*?^};', 'm'));
    if (match) return match[0].replace(name + ' = function', 'function ' + name).replace(/\bexit;/g,'return;').slice(0,-1);
  }
  assert(match, name + ' missing');
  return match[0];
}
function track(id) { return {id, name:id, singer:''}; }
function fixture(queue, current, incoming, selected = 0) {
  const texts = [];
  const c = {
    array_length:a=>a.length, array_push:(a,x)=>a.push(x),
    array_contains:(a,x)=>a.includes(x), string:String,
    ds_map_find_value:(a,k)=>a[k], json_parse:JSON.parse,
    is_struct:x=>x !== null && typeof x === 'object', variable_struct_exists:(o,k)=>Object.hasOwn(o,k),
    qqm_text:x=>x, qqm_get:()=>1,
    qqm_queue:queue.map(track), qqm_play_index:current,
    qqm_play_id:current>=0 ? queue[current] : '',
    qqm_tracks:incoming.map(track), qqm_list_kind:'playlist',
    qqm_pl_id:'new', qqm_queue_pl_id:'old', qqm_pl_name:'New playlist',
    qqm_queue_name:'Old playlist', qqm_list_is_queue:0,
    qqm_play_from_queue(i) { this.qqm_play_index = i; this.qqm_play_id=this.qqm_queue[i].id; },
    qqm_req_source:'qq', qqm_lists_pending:0, qqm_req:7, qqm_kind:'playlist', qqm_req_life:0, qqm_loading:0,
    qqm_open:0, qqm_ready:1, qqm_logged:0, qqm_source:'qq', qqm_saw_status:1,
    fontCJK:0, fa_middle:0, fa_center:0, fa_right:0, c_white:0, c_red:1,
    button_collision:()=>false, button_click:()=>false,
    draw_set_font:()=>{}, draw_set_valign:()=>{}, draw_set_halign:()=>{},
    draw_set_alpha:()=>{}, draw_roundrect:()=>{}, draw_set_color:()=>{},
    draw_text_transformed:(x,y,text)=>texts.push(text), texts,
  };
  // Bind the stand-in player to this context so only the queue logic is under test.
  c.qqm_play_from_queue = i => { c.qqm_play_index=i; c.qqm_play_id=c.qqm_queue[i].id; };
  vm.createContext(c);
  vm.runInContext(['qqm_play_at','qqm_async_body','qqm_draw_tabs'].map(extract).join('\n'),c);
  return c;
}
function playlistReply(c, tracks) {
  c.qqm_async_body({id:7,status:0,result:JSON.stringify({tracks:tracks.map(track),name:'New playlist'})});
}
let checks=0;
function test(name, fn) { fn(); checks++; console.log('PASS ' + name); }
test('browsing a new playlist preserves the active queue position',()=>{
  const c=fixture(['A','B','C'],1,['X','Y']);
  playlistReply(c,['X','Y']);
  assert.equal(c.qqm_play_index,1);
  c.qqm_play_at(0);
  assert.deepEqual(Array.from(c.qqm_queue,t=>t.id),['A','B','X','Y','C']);
  assert.equal(c.qqm_play_id,'X');
});
for (const scenario of [
  {name:'selected row in middle of new playlist',q:['A','B','C'],cur:1,p:['X','Y','Z'],pick:1,want:['A','B','X','Y','Z','C'],play:'Y'},
  {name:'insert after final playing track',q:['A','B'],cur:1,p:['X','Y'],pick:0,want:['A','B','X','Y'],play:'X'},
  {name:'no active queue position inserts before old entries',q:['A','B'],cur:-1,p:['X','Y'],pick:1,want:['X','Y','A','B'],play:'Y'},
  {name:'empty queue uses playlist',q:[],cur:-1,p:['X','Y'],pick:1,want:['X','Y'],play:'Y'},
  {name:'overlapping songs move with the new playlist',q:['A','B','C','D'],cur:1,p:['C','X','D'],pick:0,want:['A','B','C','X','D'],play:'C'},
  {name:'active song remains the insertion anchor when also in new playlist',q:['A','B','C','D'],cur:1,p:['X','B','Y'],pick:0,want:['A','B','X','Y','C','D'],play:'X'},
  {name:'new playlist repeated song appears once',q:['A','B','C'],cur:1,p:['X','X','Y'],pick:1,want:['A','B','X','Y','C'],play:'X'},
]) test(scenario.name,()=>{
  const s=scenario,c=fixture(s.q,s.cur,s.p);
  c.qqm_play_at(s.pick);
  assert.deepEqual(Array.from(c.qqm_queue,t=>t.id),s.want);
  assert.equal(c.qqm_play_id,s.play);
});
test('same playlist jumps without duplicating the queue',()=>{
  const c=fixture(['A','X','Y','B'],1,['X','Y']);
  c.qqm_queue_pl_id='new'; c.qqm_play_at(1);
  assert.deepEqual(Array.from(c.qqm_queue,t=>t.id),['A','X','Y','B']);
  assert.equal(c.qqm_play_id,'Y');
});
for (const s of [
  {name:'local page hides signed-out hint',open:0,ready:1,logged:0,hint:null},
  {name:'local page hides offline hint',open:0,ready:-1,logged:0,hint:null},
  {name:'QQ page shows signed-out hint only after status reply',open:1,ready:1,logged:0,hint:'nologin'},
  {name:'QQ page loading does not claim signed out',open:1,ready:0,logged:0,hint:null},
  {name:'QQ page shows offline hint',open:1,ready:-1,logged:0,hint:'offline'},
  {name:'signed-in QQ page has no warning',open:1,ready:1,logged:1,hint:null},
]) test(s.name,()=>{
  const c=fixture([], -1, []); Object.assign(c,{qqm_open:s.open,qqm_ready:s.ready,qqm_logged:s.logged});
  c.qqm_draw_tabs();
  const hints=c.texts.filter(x=>x==='nologin'||x==='offline');
  assert.deepEqual(hints,s.hint?[s.hint]:[]);
});
console.log(`${checks} checks passed`);
