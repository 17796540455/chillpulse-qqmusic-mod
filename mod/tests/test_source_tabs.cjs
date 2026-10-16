const fs=require('fs'), vm=require('vm'), assert=require('assert/strict'), path=require('path');
const source=fs.readFileSync(process.argv[2] || path.join(__dirname,'..','gml_Script_qqm_mod.gml'),'utf8');
function extract(name) {
  let m=source.match(new RegExp('^function '+name+'\\([^]*?^}', 'm'));
  if (!m) {
    m=source.match(new RegExp('^'+name+' = function\\([^]*?^};','m'));
    assert(m,name);
    return m[0].replace(name+' = function','function '+name).replace(/\bexit;/g,'return;').slice(0,-1)
      .replace(/qqm_prep_frames div 60/g,'Math.floor(qqm_prep_frames / 60)');
  }
  return m[0].replace(/qqm_prep_frames div 60/g,'Math.floor(qqm_prep_frames / 60)');
}
function fixture() {
  const requests=[],drawn=[];
  const c={requests,drawn,nextId:100,current_language:1,
    qqm_source:'qq',qqm_open:0,qqm_view:0,qqm_req:-1,qqm_kind:'',qqm_req_source:'qq',qqm_req_life:0,
    qqm_lists_pending:0,qqm_pending_play:-1,qqm_ready:1,qqm_logged:1,qqm_saw_status:1,
    qqm_base:'http://127.0.0.1:38612',qqm_status:'',qqm_loading:0,
    qqm_playlists:[],qqm_tracks:[],qqm_list_kind:'',qqm_scroll:0,qqm_search_focus:0,
    qqm_play_id:'',qqm_play_state:'',qqm_sound:-1,qqm_queue:[],qqm_play_index:-1,
    qqm_online_active:0,qqm_play_generation:0,qqm_req_play_generation:0,
    qqm_demo:0,qqm_hud_timer:-1,qqm_toast_time:0,qqm_prefetch_cd:0,qqm_prefetch_q:0,
    qqm_hover_prefetch:0,qqm_hovered:-1,qqm_hover_frames:0,
    string:String,string_copy:(s,p,n)=>s.slice(p-1,p-1+n),string_pos:(s,t)=>t.indexOf(s)+1,
    array_length:a=>a.length,ds_map_find_value:(m,k)=>m[k],json_parse:JSON.parse,
    is_struct:o=>o!==null&&typeof o==='object',variable_struct_exists:(o,k)=>Object.hasOwn(o,k),
    fontCJK:0,fa_middle:0,fa_center:0,fa_right:0,c_red:1,c_white:0,
    mb_left:0,mouse_check_button_pressed:()=>false,
    button_collision:(x)=>c.clickX===x,
    button_click:(x)=>{if(c.clickX!==x)return false;c.clickX=null;return true;},
    draw_set_font:()=>{},draw_set_valign:()=>{},draw_set_halign:()=>{},draw_set_alpha:()=>{},
    draw_roundrect:()=>{},draw_set_color:()=>{},draw_text_transformed:(x,y,t)=>drawn.push(t),
    qqm_start_stream:f=>{c.started=f;},qqm_fail_play:m=>{c.failed=m;},
  };
  c.http_get=url=>{const id=c.nextId++; requests.push({url,id});return id;};
  vm.createContext(c);
  vm.runInContext(['qqm_text','qqm_get','qqm_try_load_lists','qqm_select_source',
                   'qqm_async_body','qqm_draw_tabs','qqm_step_body'].map(extract).join('\n'),c);
  return c;
}
function reply(c,payload,status=0,id=c.qqm_req) {
  c.qqm_async_body({id,status,result:typeof payload==='string'?payload:JSON.stringify(payload)});
}
function lists(name){return {ok:true,logged_in:true,playlists:[{id:name,name,count:1}]};}
let count=0;
function test(name,fn){fn();count++;console.log('PASS '+name);}
for(const [service,x] of [['qq',110],['ne',190]]) test(service+' tab fetches playlists on the first click',()=>{
  const c=fixture();c.clickX=x;c.qqm_draw_tabs();
  assert.equal(c.qqm_source,service);assert.equal(c.qqm_view,0);
  assert.equal(c.requests.length,1);assert.match(c.requests[0].url,new RegExp('/playlists\\?src='+service+'$'));
  reply(c,lists(service));assert.equal(c.qqm_playlists[0].name,service);assert.equal(c.qqm_status,'');
});
test('in-progress HTTP event preserves request and connection state',()=>{
  const c=fixture();c.qqm_select_source('ne');const id=c.qqm_req;
  reply(c,'unfinished JSON',1);assert.equal(c.qqm_req,id);assert.equal(c.qqm_ready,1);
  reply(c,lists('ne'),0,id);assert.equal(c.qqm_playlists[0].name,'ne');
});
test('stale QQ success cannot replace selected NetEase playlists',()=>{
  const c=fixture();c.qqm_select_source('qq');const old=c.qqm_req;
  c.qqm_select_source('ne');assert.equal(c.requests.length,1);
  reply(c,lists('qq'),0,old);assert.equal(c.requests.length,2);
  assert.match(c.requests[1].url,/src=ne$/);assert.equal(c.qqm_playlists.length,0);
  reply(c,lists('ne'));assert.equal(c.qqm_playlists[0].name,'ne');
});
test('stale QQ transport error cannot flag NetEase as disconnected',()=>{
  const c=fixture();c.qqm_select_source('qq');const old=c.qqm_req;
  c.qqm_select_source('ne');reply(c,'',-1,old);
  assert.equal(c.qqm_ready,1);assert.equal(c.qqm_status,'加载中...');assert.equal(c.requests.length,2);
});
test('returning to the same service ignores its previous search reply',()=>{
  const c=fixture();c.qqm_source='qq';c.qqm_open=1;
  c.qqm_get('/search?q=old','search');const old=c.qqm_req;
  c.qqm_select_source('qq');reply(c,{ok:true,tracks:[{id:'old'}]},0,old);
  assert.equal(c.qqm_view,0);assert.equal(c.qqm_tracks.length,0);
  assert.equal(c.requests.length,2);assert.match(c.requests[1].url,/playlists\?src=qq$/);
});
test('rapid QQ to NetEase to QQ only loads the final selected service',()=>{
  const c=fixture();c.qqm_select_source('qq');c.qqm_select_source('ne');c.qqm_select_source('qq');
  reply(c,lists('qq'));c.qqm_step_body();
  assert.equal(c.requests.length,2);assert.match(c.requests[1].url,/src=qq$/);
  assert(c.requests.every(r=>!r.url.includes('src=ne')));
});
test('tab load waits through a busy playback request and retries next frame',()=>{
  const c=fixture();c.qqm_get('/playstate?id=ne:123','poll');const old=c.qqm_req;
  c.qqm_select_source('ne');assert.equal(c.requests.length,1);
  reply(c,{ok:true,state:'preparing'},0,old);c.qqm_step_body();
  assert.equal(c.requests.length,2);assert.match(c.requests[1].url,/playlists\?src=ne$/);
});
test('queued user playback keeps priority over playlist loading',()=>{
  const c=fixture();c.qqm_pending_play=1;c.qqm_select_source('ne');
  assert.equal(c.requests.length,0);c.qqm_pending_play=-1;c.qqm_try_load_lists();
  assert.equal(c.requests.length,1);
});
test('returning from search or queue opens the playlist view',()=>{
  const c=fixture();c.qqm_view=2;c.qqm_select_source('qq');assert.equal(c.qqm_view,0);
  reply(c,lists('qq'));c.qqm_open=2;c.qqm_view=3;c.qqm_select_source('qq');
  assert.equal(c.qqm_open,1);assert.equal(c.qqm_view,0);assert.equal(c.requests.length,2);
});
test('local tab cancels an unsent automatic playlist load',()=>{
  const c=fixture();c.qqm_get('/playstate?id=123','poll');c.qqm_select_source('ne');
  c.clickX=30;c.qqm_draw_tabs();assert.equal(c.qqm_open,0);assert.equal(c.qqm_lists_pending,0);
  reply(c,{ok:true,state:'preparing'});c.qqm_step_body();assert.equal(c.requests.length,1);
});
test('a completed service error is shown without a false disconnect',()=>{
  const c=fixture();c.qqm_select_source('ne');reply(c,{ok:false,msg:'需要网易云登录'});
  assert.equal(c.qqm_ready,1);assert.equal(c.qqm_status,'需要网易云登录');c.qqm_step_body();
  assert.equal(c.requests.length,1);
});
test('NetEase login state is taken from its own playlist response',()=>{
  const c=fixture();c.qqm_logged=0;c.qqm_select_source('ne');reply(c,lists('ne'));
  assert.equal(c.qqm_logged,true);assert.equal(c.qqm_saw_status,1);
});
test('real connection failure names the active service and recovers on retry',()=>{
  const c=fixture();c.qqm_select_source('ne');reply(c,'',-1);
  assert.equal(c.qqm_status,'未连接网易云音乐服务');assert.equal(c.qqm_ready,-1);
  c.qqm_select_source('ne');reply(c,lists('ne'));assert.equal(c.qqm_ready,1);assert.equal(c.qqm_status,'');
  c.qqm_source='qq';assert.equal(c.qqm_text('offline'),'未连接QQ音乐服务');
});
test('playback result is still handled after switching display service',()=>{
  const c=fixture();c.qqm_get('/play?id=qqsong','play');const old=c.qqm_req;
  c.qqm_select_source('ne');reply(c,{ok:true,state:'ready',file:'qqmusic_cache/song.ogg'},0,old);
  assert.equal(c.started,'qqmusic_cache/song.ogg');c.qqm_step_body();assert.equal(c.requests.length,2);
});
console.log(count+' source-tab checks passed');
