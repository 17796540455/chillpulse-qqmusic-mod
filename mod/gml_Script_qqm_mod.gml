// ============================================================================
//  ChillPulse QQ Music mod  -  in-game QQ Music panel for the music player
//  Injected by apply_mod.csx.  All functions are global (GMS 2.3+ semantics).
// ============================================================================

/// @description Initialise QQ Music mod state on obj_controller.
function qqm_init()
{
    qqm_port         = 38612;
    qqm_base         = "http://127.0.0.1:" + string(qqm_port);
    qqm_open         = 0;      // 1 = QQ panel shown inside the music panel
    qqm_view         = 0;      // 0 = playlists, 1 = tracks, 2 = search
    qqm_rows         = 6;      // rows visible in the panel
    qqm_req          = -1;     // id of the http request in flight
    qqm_kind         = "";     // what that request was for
    qqm_req_life     = 0;      // step counter guarding against a lost response

    qqm_status       = "";
    qqm_toast        = "";
    qqm_toast_time   = 0;

    qqm_tracks       = [];
    qqm_playlists    = [];
    qqm_pl_name      = "";
    qqm_scroll       = 0;

    qqm_query        = "";
    qqm_search_focus = 0;
    qqm_caret        = 0;

    qqm_play_id      = "";
    qqm_play_file    = "";
    qqm_play_title   = "";
    qqm_play_singer  = "";
    qqm_play_state   = "";
    qqm_play_index   = -1;
    qqm_play_frames  = 0;
    qqm_sound        = -1;
    qqm_playing      = 1;
    qqm_poll         = 0;

    qqm_ready        = 0;      // 0 unknown, 1 bridge reachable, -1 not reachable
    qqm_logged       = 0;
    qqm_saw_status   = 0;      // 1 once the bridge has actually answered once
    qqm_ffmpeg       = 0;
    qqm_loading      = 0;

    // --- self test / diagnostics -------------------------------------------
    // The HUD is only shown while the first-run self test is active, so a
    // normal session is completely clean.
    qqm_hud          = 0;
    qqm_hud_timer    = -1;
    qqm_demo         = 0;      // scripted first-run self test
    qqm_demo_step    = 0;
    qqm_demo_timer   = 150;
    qqm_demo_wait    = 0;
    qqm_demo_tries   = 0;
    qqm_pending_play = -1;     // track index whose /play still needs sending
    qqm_dead         = [];     // mids that failed to play this session
    qqm_demo_pick    = -1;
    qqm_saved_music  = -1;     // local sound asset that was playing when QQ took over
    qqm_prefetch_id  = "";     // next track, pre-encoded by the bridge
    qqm_prefetch_q   = 0;      // 1 = prefetch request still needs sending
    qqm_prefetch_cd  = 0;      // cooldown so we never flood the bridge
    qqm_hover_prefetch = 0;    // hover prefetch is off until the bridge is known
                               // to never let a prefetch disturb a play
    qqm_prep_frames  = 0;      // how long the current track has been preparing
    // --- look-ahead prefetch -------------------------------------------------
    // The bridge has exactly ONE prefetch slot (a newer prefetch replaces the
    // running one), so the game paces them: warm a track, wait until it is
    // ready, then warm the following one.
    qqm_prefetch_ahead = 3;    // how many upcoming tracks to keep warm
    qqm_pf_next        = -1;   // next queue index worth warming
    qqm_pf_idx         = -1;   // queue index currently being warmed
    qqm_pf_target      = "";   // its mid
    qqm_pf_waiting     = 0;    // 1 while warming / checking one
    qqm_pf_poll        = 0;    // countdown to the next readiness check
    qqm_hover_last   = -1;     // row the mouse is resting on
    qqm_hover_frames = 0;
    qqm_queue        = [];     // the list playback walks through
    qqm_queue_name   = "";     // where that queue came from
    qqm_queue_pl_id  = "";     // playlist id that contributed to the queue
    qqm_pl_id        = "";     // playlist currently shown in the panel
    qqm_list_is_queue = 0;     // 1 when the displayed list IS the queue
    qqm_list_kind    = "";     // "search" or "playlist" - what the shown list is
    qqm_clicks       = 0;
    qqm_hovered      = -1;
    qqm_err          = "";
    qqm_err_count    = 0;
    try
    {
        if (!file_exists("qqmusic_cache/demo_done"))
        {
            qqm_demo = 1;
            qqm_hud = 1;
        }
    }
    catch (_e)
    {
        qqm_demo = 1;
        qqm_hud = 1;
    }

    // Adopt a stream that outlived a controller rebuild (room change) so that
    // music never keeps playing with no way to control it.
    if (variable_global_exists("qqm_stream"))
    {
        if (global.qqm_stream != -1)
        {
            qqm_sound = global.qqm_stream;
            qqm_play_state = "playing";
            qqm_play_title = "QQ音乐";
        }
    }
    global.qqm_stream = qqm_sound;
}

/// @description Localised UI labels (Chinese for the CJK languages, English otherwise).
function qqm_text(_key)
{
    var _cn = (current_language == 1 || current_language == 2 || current_language == 3);
    switch (_key)
    {
        case "tab_local": return _cn ? "本地音乐" : "Local";
        case "tab_qq":    return "QQ音乐";
        case "playlist":  return _cn ? "歌单" : "Lists";
        case "queue":     return _cn ? "队列" : "Queue";
        case "reordered": return _cn ? "已调整顺序" : "Reordered";
        case "removed":   return _cn ? "已移出队列" : "Removed";
        case "single":    return _cn ? "单曲" : "Single";
        case "only_one":  return _cn ? "队列仅此一首" : "Only one track queued";
        case "from_search": return _cn ? "搜索结果" : "Search";
        case "queue_empty": return _cn ? "还没有播放内容" : "Nothing played yet";
        case "search":    return _cn ? "搜索" : "Search";
        case "loading":   return _cn ? "加载中..." : "Loading...";
        case "empty":     return _cn ? "暂无内容" : "No content";
        case "offline":   return _cn ? "未连接QQ音乐服务" : "QQ Music service offline";
        case "buffering": return _cn ? "缓冲中..." : "Buffering...";
        case "hint":      return _cn ? "输入歌名或歌手" : "Type a song or artist";
        case "nologin":   return _cn ? "未登录：仅能播放免费歌曲" : "Not signed in - free tracks only";
        case "failed":    return _cn ? "加载失败" : "Request failed";
        case "badreply":  return _cn ? "服务返回异常" : "Bad reply";
        case "noaudio":   return _cn ? "音频加载失败" : "Audio load failed";
        case "playing":   return _cn ? "正在播放" : "Playing";
        case "vip":       return "VIP";
    }
    return _key;
}

/// @description UTF-8 percent encoder.  GameMaker 2 dropped the GM8-era
/// url_encode(), so query strings are encoded here by hand.
function qqm_urlenc(_s)
{
    var _hex = "0123456789ABCDEF";
    var _out = "";
    var _n = string_length(_s);
    for (var i = 1; i <= _n; i++)
    {
        var _c = string_char_at(_s, i);
        var _o = ord(_c);
        if ((_o >= 48 && _o <= 57) || (_o >= 65 && _o <= 90) || (_o >= 97 && _o <= 122)
            || _o == 45 || _o == 95 || _o == 46 || _o == 126)
        {
            _out += _c;
        }
        else if (_o < 128)
        {
            _out += "%" + string_char_at(_hex, (_o >> 4) + 1) + string_char_at(_hex, (_o & 15) + 1);
        }
        else if (_o < 2048)
        {
            var _b1 = 192 | (_o >> 6);
            var _b2 = 128 | (_o & 63);
            _out += "%" + string_char_at(_hex, (_b1 >> 4) + 1) + string_char_at(_hex, (_b1 & 15) + 1);
            _out += "%" + string_char_at(_hex, (_b2 >> 4) + 1) + string_char_at(_hex, (_b2 & 15) + 1);
        }
        else if (_o < 65536)
        {
            var _c1 = 224 | (_o >> 12);
            var _c2 = 128 | ((_o >> 6) & 63);
            var _c3 = 128 | (_o & 63);
            _out += "%" + string_char_at(_hex, (_c1 >> 4) + 1) + string_char_at(_hex, (_c1 & 15) + 1);
            _out += "%" + string_char_at(_hex, (_c2 >> 4) + 1) + string_char_at(_hex, (_c2 & 15) + 1);
            _out += "%" + string_char_at(_hex, (_c3 >> 4) + 1) + string_char_at(_hex, (_c3 & 15) + 1);
        }
        else
        {
            var _d1 = 240 | (_o >> 18);
            var _d2 = 128 | ((_o >> 12) & 63);
            var _d3 = 128 | ((_o >> 6) & 63);
            var _d4 = 128 | (_o & 63);
            _out += "%" + string_char_at(_hex, (_d1 >> 4) + 1) + string_char_at(_hex, (_d1 & 15) + 1);
            _out += "%" + string_char_at(_hex, (_d2 >> 4) + 1) + string_char_at(_hex, (_d2 & 15) + 1);
            _out += "%" + string_char_at(_hex, (_d3 >> 4) + 1) + string_char_at(_hex, (_d3 & 15) + 1);
            _out += "%" + string_char_at(_hex, (_d4 >> 4) + 1) + string_char_at(_hex, (_d4 & 15) + 1);
        }
    }
    return _out;
}

/// @description Swap two queue entries (the ▲▼ buttons in the queue view).
function qqm_queue_move(_from, _to)
{
    var _n = array_length(qqm_queue);
    if (_from < 0 || _from >= _n || _to < 0 || _to >= _n || _from == _to)
    {
        return;
    }
    var _tmp = qqm_queue[_from];
    qqm_queue[_from] = qqm_queue[_to];
    qqm_queue[_to] = _tmp;
    // the "now playing" marker must stay on the same song
    if (qqm_play_index == _from)
    {
        qqm_play_index = _to;
    }
    else if (qqm_play_index == _to)
    {
        qqm_play_index = _from;
    }
    qqm_status = qqm_text("reordered");
}

/// @description Drop a queue entry (the × button in the queue view).
function qqm_queue_remove(_idx)
{
    var _n = array_length(qqm_queue);
    if (_idx < 0 || _idx >= _n)
    {
        return;
    }
    array_delete(qqm_queue, _idx, 1);
    if (_idx < qqm_play_index)
    {
        qqm_play_index -= 1;
    }
    else if (_idx == qqm_play_index)
    {
        // the song keeps playing, it is just no longer in the queue
        qqm_play_index = -1;
    }
    qqm_scroll = clamp(qqm_scroll, 0, max(0, array_length(qqm_queue) - qqm_rows));
    qqm_status = qqm_text("removed");
}

/// @description Fire one bridge request (single request in flight).
function qqm_get(_path, _kind)
{
    if (qqm_req != -1)
    {
        return 0;
    }
    qqm_kind = _kind;
    qqm_req_life = 0;
    qqm_req = http_get(qqm_base + _path);
    return 1;
}

/// @description Stop and release the current QQ stream.
function qqm_stop()
{
    if (qqm_sound != -1)
    {
        audio_stop_sound(qqm_sound);
        audio_destroy_stream(qqm_sound);
        qqm_sound = -1;
    }
    global.qqm_stream = -1;
    qqm_pending_play = -1;
    qqm_play_state = "";
    qqm_play_file = "";
    qqm_play_title = "";
    qqm_play_singer = "";
    qqm_play_id = "";
    qqm_play_frames = 0;
}

/// @description Play a row of the list on screen.
/// Both the playlists and the search results *splice into* the existing queue
/// right behind the song that is playing, and the clicked song starts at once:
/// nothing already queued is thrown away, and when the new material ends the
/// queue carries on exactly where the listener left off.
function qqm_play_at(_i)
{
    if (_i < 0 || _i >= array_length(qqm_tracks))
    {
        return;
    }
    var _t = qqm_tracks[_i];
    var _tid = string(_t.id);
    var _have = array_length(qqm_queue);

    if (qqm_list_kind == "playlist")
    {
        // (a) this playlist already IS the queue: just jump to the song
        if (_have > 0 && qqm_pl_id != "" && qqm_pl_id == qqm_queue_pl_id)
        {
            for (var m = 0; m < _have; m++)
            {
                if (string(qqm_queue[m].id) == _tid)
                {
                    qqm_play_from_queue(m);
                    return;
                }
            }
        }

        // (b) nothing queued yet: the playlist simply becomes the queue
        if (_have == 0)
        {
            qqm_queue = qqm_tracks;
            qqm_queue_name = qqm_pl_name;
            qqm_queue_pl_id = qqm_pl_id;
            qqm_list_is_queue = 1;
            qqm_play_from_queue(_i);
            return;
        }

        // (c) another queue is playing: splice this playlist in behind the
        //     playing song and jump to the clicked track
        var _cur = qqm_play_index;
        var _seen = [];
        for (var a = 0; a < _have; a++)
        {
            array_push(_seen, string(qqm_queue[a].id));
        }
        if (array_contains(_seen, _tid))
        {
            // it is already queued somewhere: jump there rather than duplicating
            for (var a2 = 0; a2 < _have; a2++)
            {
                if (string(qqm_queue[a2].id) == _tid)
                {
                    qqm_play_from_queue(a2);
                    return;
                }
            }
        }
        var _newq = [];
        var _at = 0;
        var _done = 0;
        for (var b = 0; b < _have; b++)
        {
            array_push(_newq, qqm_queue[b]);
            if (_done == 0 && b == _cur)
            {
                for (var c = 0; c < array_length(qqm_tracks); c++)
                {
                    var _cm = string(qqm_tracks[c].id);
                    if (array_contains(_seen, _cm))
                    {
                        continue;                   // already queued, do not duplicate
                    }
                    if (c == _i)
                    {
                        _at = array_length(_newq);
                    }
                    array_push(_newq, qqm_tracks[c]);
                    array_push(_seen, _cm);
                }
                _done = 1;
            }
        }
        if (_done == 0)
        {
            // No playable position (nothing playing, or the playhead is stale):
            // the playlist goes in FRONT of whatever is queued - the comment
            // always said so, but the code used to append it to the end.
            var _front = [];
            var _fat = 0;
            for (var c2 = 0; c2 < array_length(qqm_tracks); c2++)
            {
                var _cm2 = string(qqm_tracks[c2].id);
                if (array_contains(_seen, _cm2))
                {
                    continue;
                }
                if (c2 == _i)
                {
                    _fat = array_length(_front);
                }
                array_push(_front, qqm_tracks[c2]);
                array_push(_seen, _cm2);
            }
            var _tail = _newq;
            _newq = [];
            for (var d = 0; d < array_length(_front); d++)
            {
                array_push(_newq, _front[d]);
            }
            for (var e = 0; e < array_length(_tail); e++)
            {
                array_push(_newq, _tail[e]);
            }
            _at = _fat;
        }
        qqm_queue = _newq;
        qqm_queue_name = qqm_pl_name;
        qqm_queue_pl_id = qqm_pl_id;
        qqm_list_is_queue = 0;
        qqm_play_from_queue(_at);
        return;
    }

    // ---- picked out of the search results ----
    // Insert it directly behind the song that is playing and jump to it, so it
    // starts at once and, when it ends, the queue carries on exactly where the
    // listener left off.  An existing copy of the song is moved rather than
    // duplicated.
    var _cur2 = qqm_play_index;
    var _newq2 = [];
    var _at2 = 0;
    var _placed = 0;
    for (var k = 0; k < _have; k++)
    {
        if (string(qqm_queue[k].id) == _tid)
        {
            continue;                       // drop the old copy
        }
        if (_placed == 0 && k > _cur2)       // right after the playing song
        {
            _at2 = array_length(_newq2);
            array_push(_newq2, _t);
            _placed = 1;
        }
        array_push(_newq2, qqm_queue[k]);
    }
    if (_placed == 0)
    {
        _at2 = array_length(_newq2);          // nothing playing, or it was last
        array_push(_newq2, _t);
    }
    qqm_queue = _newq2;
    if (qqm_queue_name == "")
    {
        qqm_queue_name = qqm_text("single");
    }
    qqm_list_is_queue = 0;
    qqm_play_from_queue(_at2);
}

/// @description Start playing index _i of the play queue.
function qqm_play_from_queue(_i)
{
    if (_i < 0 || _i >= array_length(qqm_queue))
    {
        return;
    }
    var _t = qqm_queue[_i];
    qqm_stop();
    qqm_play_index = _i;
    qqm_play_id = string(_t.id);
    qqm_play_title = string(_t.name);
    qqm_play_singer = string(_t.singer);
    qqm_play_state = "requesting";
    qqm_status = qqm_text("buffering");
    qqm_prep_frames = 0;
    qqm_poll = 0;
    qqm_pending_play = 1;   // flag: needs sending, retried while the channel is busy
    qqm_try_send_play();
}

/// @description Send the queued /play request once the channel is free.
function qqm_try_send_play()
{
    if (qqm_pending_play < 0 || qqm_play_state != "requesting")
    {
        return;
    }
    if (qqm_get("/play?id=" + qqm_urlenc(qqm_play_id)
              + "&name=" + qqm_urlenc(qqm_play_title)
              + "&singer=" + qqm_urlenc(qqm_play_singer), "play") == 1)
    {
        qqm_pending_play = -1;
        qqm_play_state = "preparing";
    }
}

/// @description Move the play position by _d tracks through the play queue.
function qqm_shift(_d)
{
    var _n = array_length(qqm_queue);
    if (_n == 0)
    {
        return;
    }
    if (_n == 1)
    {
        // a single song was queued (picked out of the search results)
        qqm_status = qqm_text("only_one");
        return;
    }
    var _i = qqm_play_index;
    if (_i < 0)
    {
        _i = 0;
    }
    _i += _d;
    if (_i < 0)
    {
        _i = _n - 1;
    }
    if (_i >= _n)
    {
        _i = 0;
    }
    qqm_play_from_queue(_i);
}

/// @description Title shown in the game's own player bar.
function qqm_bar_title()
{
    if (qqm_play_title != "")
    {
        if (qqm_play_singer != "")
        {
            return qqm_play_title + " - " + qqm_play_singer;
        }
        return qqm_play_title;
    }
    if (array_length(music_names) > 0 && current_music_index >= 0
        && current_music_index < array_length(music_names))
    {
        return music_names[current_music_index];
    }
    return "";
}

/// @description Shorten a string so it fits the panel row.
function qqm_clip(_s)
{
    _s = string(_s);
    if (string_length(_s) > 42)
    {
        _s = string_copy(_s, 1, 40) + "..";
    }
    return _s;
}

/// @description Step wrapper: a mod error must never break the game.
function qqm_step()
{
    try
    {
        qqm_step_body();
    }
    catch (_e)
    {
        qqm_err = "step: " + string(_e.message) + " L" + string(_e.line);
        qqm_err_count += 1;
    }
}

/// @description Per-step logic: player takeover, polling, search typing.
function qqm_step_body()
{
    if (mouse_check_button_pressed(mb_left))
    {
        qqm_clicks += 1;
    }
    if (qqm_demo == 1)
    {
        qqm_demo_drive();
    }
    if (qqm_hud_timer > 0)
    {
        qqm_hud_timer -= 1;
        if (qqm_hud_timer == 0)
        {
            qqm_hud = 0;
        }
    }
    if (qqm_toast_time > 0)
    {
        qqm_toast_time -= 1;
        if (qqm_toast_time <= 0)
        {
            qqm_toast = "";
        }
    }
    if (qqm_req != -1)
    {
        qqm_req_life += 1;
        // QQ's search endpoint can stall for ~10s while it retries, so the
        // client budget has to be comfortably longer than the bridge's.
        if (qqm_req_life > 2400)
        {
            qqm_req = -1;
            qqm_kind = "";
            qqm_status = qqm_text("failed");
            qqm_loading = 0;
        }
    }

    // ---- the game's player bar drives the QQ stream while one is loaded ----
    var _on = (qqm_sound != -1 || qqm_play_state == "preparing");
    if (qqm_sound != -1 && current_music != qqm_saved_music
        && audio_is_playing(current_music))
    {
        // the player deliberately started a local cassette (the QQ stream never
        // changes current_music), so hand control back to the game
        qqm_stop();
        _on = false;
    }
    if (_on)
    {
        var _mx = device_mouse_x_to_gui(0);
        var _my = device_mouse_y_to_gui(0);
        // The player bar sits at y 660-700 and never overlaps the music panel
        // (y 360-640), so these hitboxes must stay live while it is open.
        if (mouse_check_button_pressed(mb_left) && !page_customization)
        {
            if (_mx >= 374 && _my >= 660 && _mx <= 420 && _my <= 700)
            {
                music_playing *= -1;
            }
            else if (_mx >= 325 && _my >= 660 && _mx <= 356 && _my <= 700)
            {
                qqm_shift(-1);
            }
            else if (_mx >= 430 && _my >= 660 && _mx <= 462 && _my <= 700)
            {
                qqm_shift(1);
            }
        }
        if (qqm_sound != -1)
        {
            audio_sound_gain(qqm_sound, slider_x / 100, 10);
            if (music_playing == -1 && qqm_playing == 1)
            {
                audio_pause_sound(qqm_sound);
                qqm_playing = -1;
            }
            else if (music_playing == 1 && qqm_playing == -1)
            {
                audio_resume_sound(qqm_sound);
                qqm_playing = 1;
            }
            if (qqm_play_frames > 0)
            {
                qqm_play_frames -= 1;
            }
            else if (music_playing == 1 && !audio_is_playing(qqm_sound))
            {
                qqm_shift(1);
            }
        }
    }

    // ---- poll the bridge while a track is being prepared ----
    if (qqm_play_state == "preparing" && qqm_play_id != "")
    {
        qqm_prep_frames += 1;
        qqm_status = qqm_text("buffering") + " " + string(qqm_prep_frames div 60) + "s";
        qqm_poll -= 1;
        if (qqm_poll <= 0)
        {
            qqm_poll = 20;
            qqm_get("/playstate?id=" + qqm_urlenc(qqm_play_id), "poll");
        }
    }

    // ---- retry a play request that could not be sent yet ----
    if (qqm_pending_play >= 0)
    {
        qqm_try_send_play();
    }

    // ---- look-ahead prefetch: keep the next few queue entries warm ----------
    if (array_length(qqm_queue) > 1 && qqm_play_index >= 0)
    {
        var _pf_idle = (qqm_req == -1 && qqm_pending_play < 0
                        && qqm_play_state != "requesting" && qqm_play_state != "preparing");
        if (qqm_pf_next <= qqm_play_index)
        {
            qqm_pf_next = qqm_play_index + 1;
        }
        // 1) check whether the track we are warming has finished
        if (qqm_pf_waiting == 1 && _pf_idle && qqm_pf_target != "")
        {
            qqm_pf_poll -= 1;
            if (qqm_pf_poll <= 0)
            {
                qqm_pf_poll = 90;
                qqm_get("/playstate?id=" + qqm_urlenc(qqm_pf_target), "pfcheck");
            }
        }
        // 2) otherwise start warming the next one in the window
        if (qqm_pf_waiting == 0 && _pf_idle)
        {
            var _pf_end = min(qqm_play_index + qqm_prefetch_ahead,
                              array_length(qqm_queue) - 1);
            if (qqm_pf_next <= _pf_end)
            {
                qqm_pf_idx = qqm_pf_next;
                qqm_pf_target = string(qqm_queue[qqm_pf_idx].id);
                qqm_pf_waiting = 1;
                qqm_pf_poll = 150;
                qqm_get("/prefetch?id=" + qqm_urlenc(qqm_pf_target), "prefetch");
            }
        }
    }

    // ---- hover prefetch: warm whatever the mouse rests on, so click-to-play
    //      feels instant while browsing.  Heavily rate limited: a long dwell,
    //      a cooldown after every request, and nothing at all while a track is
    //      playing/pending - an over-eager prefetch both wastes bandwidth and
    //      gets the upstream API to throttle us. ----
    if (qqm_prefetch_cd > 0)
    {
        qqm_prefetch_cd -= 1;
    }
    if (qqm_hover_prefetch == 1 && qqm_view != 0 && qqm_hovered >= 0
        && qqm_hovered < array_length(qqm_tracks)
        && qqm_prefetch_q == 0 && qqm_prefetch_cd == 0 && qqm_pending_play < 0
        && qqm_play_state != "requesting" && qqm_play_state != "preparing")
    {
        if (qqm_hovered == qqm_hover_last)
        {
            qqm_hover_frames += 1;
        }
        else
        {
            qqm_hover_last = qqm_hovered;
            qqm_hover_frames = 0;
        }
        if (qqm_hover_frames >= 45)
        {
            var _hmid = string(qqm_tracks[qqm_hovered].id);
            if (_hmid != qqm_prefetch_id)
            {
                qqm_prefetch_id = _hmid;
                qqm_prefetch_q = 1;
                qqm_prefetch_cd = 180;
            }
            qqm_hover_frames = 46;
        }
    }
    else if (qqm_hovered < 0)
    {
        qqm_hover_last = -1;
        qqm_hover_frames = 0;
    }

    // ---- search box typing ----
    if (qqm_open == 1 && qqm_view == 2 && qqm_search_focus == 1)
    {
        qqm_query = keyboard_string;
        if (string_length(qqm_query) > 40)
        {
            qqm_query = string_copy(qqm_query, 1, 40);
            keyboard_string = qqm_query;
        }
        if (keyboard_check_pressed(vk_enter))
        {
            qqm_search_focus = 0;
            keyboard_string = "";
            if (string_length(qqm_query) > 0)
            {
                qqm_scroll = 0;
                qqm_loading = 1;
                qqm_status = qqm_text("loading");
                qqm_get("/search?q=" + qqm_urlenc(qqm_query) + "&n=30", "search");
            }
        }
    }
    else if (qqm_search_focus == 1)
    {
        qqm_search_focus = 0;
        keyboard_string = "";
    }
}

/// @description Async wrapper.
function qqm_async(_map)
{
    try
    {
        qqm_async_body(_map);
    }
    catch (_e)
    {
        qqm_err = "async: " + string(_e.message) + " L" + string(_e.line);
        qqm_err_count += 1;
    }
}

/// @description Handle the bridge replies inside the game's Async HTTP event.
function qqm_async_body(_map)
{
    if (qqm_req == -1)
    {
        return;
    }
    var _id = ds_map_find_value(_map, "id");
    if (_id != qqm_req)
    {
        return;
    }
    var _kind = qqm_kind;
    qqm_req = -1;
    qqm_kind = "";
    qqm_req_life = 0;
    qqm_loading = 0;

    var _status = ds_map_find_value(_map, "status");
    if (_status != 0)
    {
        qqm_status = qqm_text("offline");
        qqm_ready = -1;
        return;
    }
    var _res = ds_map_find_value(_map, "result");
    var _j = undefined;
    try
    {
        _j = json_parse(_res);
    }
    catch (_e)
    {
        qqm_status = qqm_text("badreply");
        return;
    }
    if (!is_struct(_j))
    {
        qqm_status = qqm_text("badreply");
        return;
    }
    qqm_ready = 1;

    switch (_kind)
    {
        case "status":
            qqm_ready = 1;
            qqm_logged = _j.logged_in;
            qqm_saw_status = 1;
            qqm_ffmpeg = _j.ffmpeg;
            qqm_get("/playlists", "playlists");
            break;

        case "playlists":
            qqm_playlists = _j.playlists;
            qqm_view = 0;
            qqm_scroll = 0;
            break;

        case "search":
            qqm_tracks = _j.tracks;
            qqm_view = 1;
            qqm_scroll = 0;
            qqm_list_is_queue = 0;
            qqm_list_kind = "search";
            if (array_length(qqm_tracks) == 0)
            {
                qqm_status = qqm_text("empty");
            }
            else
            {
                qqm_status = "";
            }
            break;

        case "playlist":
            qqm_tracks = _j.tracks;
            qqm_pl_name = _j.name;
            qqm_view = 1;
            qqm_scroll = 0;
            qqm_play_index = -1;
            qqm_list_is_queue = 0;
            qqm_list_kind = "playlist";
            qqm_status = "";
            // warm the first track so the first click is instant
            if (array_length(qqm_tracks) > 0)
            {
                qqm_prefetch_id = string(qqm_tracks[0].id);
                qqm_prefetch_q = 1;
            }
            break;

        case "play":
            if (_j.state == "ready")
            {
                qqm_start_stream(_j.file);
            }
            else if (_j.state == "error")
            {
                qqm_fail_play(_j.msg);
            }
            else
            {
                qqm_play_state = "preparing";
            }
            break;

        case "pfcheck":
            // did the look-ahead prefetch finish (or turn out unplayable)?
            var _pfs = "";
            if (variable_struct_exists(_j, "state"))
            {
                _pfs = string(_j.state);
            }
            if (_pfs == "ready" || _pfs == "error")
            {
                if (qqm_pf_idx >= 0)
                {
                    qqm_pf_next = qqm_pf_idx + 1;
                }
                qqm_pf_waiting = 0;
                qqm_pf_target = "";
            }
            break;

        case "poll":
            if (_j.state == "ready")
            {
                qqm_start_stream(_j.file);
            }
            else if (_j.state == "error")
            {
                qqm_fail_play(_j.msg);
            }
            break;
    }
}

/// @description Report a failed play request and clear the pending selection.
function qqm_fail_play(_msg)
{
    if (qqm_play_id != "")
    {
        array_push(qqm_dead, qqm_play_id);
    }
    qqm_play_state = "";
    qqm_pending_play = -1;
    qqm_status = string(_msg);
    qqm_play_title = "";
    qqm_play_singer = "";
    qqm_play_id = "";
    qqm_play_file = "";
    qqm_play_index = -1;
}

/// @description Mark the first-run self test as done so it never runs again.
function qqm_demo_finish()
{
    qqm_demo = 0;
    qqm_hud_timer = 900;   // keep the diagnostics up for ~15s, then hide
    try
    {
        var _f = file_text_open_write("qqmusic_cache/demo_done");
        file_text_write_string(_f, "ok");
        file_text_close(_f);
    }
    catch (_e)
    {
    }
}

/// @description Load the prepared ogg file and start it on the game's player.
function qqm_start_stream(_file)
{
    if (qqm_sound != -1)
    {
        audio_stop_sound(qqm_sound);
        audio_destroy_stream(qqm_sound);
        qqm_sound = -1;
    }
    var _rel = string(_file);
    qqm_play_file = _rel;
    // GameMaker resolves streamed audio against the game folder, but a plain
    // relative path is not always honoured - try the absolute one first, then
    // the relative path as a fallback.
    var _abs = _rel;
    if (string_pos(":", _rel) == 0)
    {
        _abs = working_directory + _rel;
    }
    qqm_sound = audio_create_stream(_abs);
    if (qqm_sound == -1 && _abs != _rel)
    {
        qqm_sound = audio_create_stream(_rel);
    }
    if (qqm_sound == -1)
    {
        qqm_play_state = "";
        if (file_exists(_abs))
        {
            qqm_status = "音频解码失败";
        }
        else
        {
            qqm_status = "找不到音频文件";
        }
        return;
    }
    qqm_play_state = "playing";
    qqm_play_frames = 30;
    qqm_playing = 1;
    music_playing = 1;
    global.qqm_stream = qqm_sound;
    // silence the cassette that was playing, otherwise both play at once
    if (audio_is_playing(current_music))
    {
        audio_stop_sound(current_music);
    }
    qqm_saved_music = current_music;
    audio_play_sound(qqm_sound, 99, false);
    audio_sound_gain(qqm_sound, slider_x / 100, 10);
    qqm_status = "";
    // start warming the tracks that follow this one
    qqm_pf_idx = -1;
    qqm_pf_target = "";
    qqm_pf_waiting = 0;
    qqm_pf_poll = 0;
    if (array_length(qqm_queue) > 1 && qqm_play_index >= 0)
    {
        qqm_pf_next = qqm_play_index + 1;
    }
    if (qqm_demo == 1)
    {
        qqm_demo_finish();
    }
}

/// @description On-screen diagnostics (test builds only).
function qqm_test_hud()
{
    var _x = 16;
    var _y = 16;
    draw_set_alpha(0.75);
    draw_set_color(c_black);
    draw_roundrect(_x - 8, _y - 8, _x + 640, _y + 200, false);
    draw_set_alpha(1);
    draw_set_color(c_white);
    draw_set_font(fontCJK);
    draw_set_halign(fa_left);
    draw_set_valign(fa_middle);
    var _i = 0;
    var _line;
    _line = "QQM TEST  clicks=" + string(qqm_clicks)
          + "  focus=" + string(window_has_focus())
          + "  music_playing=" + string(music_playing);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "mouse gui=" + string(round(device_mouse_x_to_gui(0))) + ","
          + string(round(device_mouse_y_to_gui(0)))
          + "  row_hover=" + string(qqm_hovered);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "music_list=" + string(page_music_list) + " qqm_open=" + string(qqm_open)
          + " cust=" + string(page_customization) + " diary=" + string(page_diary)
          + " scene=" + string(page_scene);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "drink=" + string(page_drink) + " stickynotes=" + string(page_stickynotes)
          + " mail=" + string(page_mail) + " phone=" + string(page_phone)
          + " cal=" + string(page_calendar);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "no_window()=" + string(no_window() == true)
          + "  tutorial=" + string(instance_exists(obj_tutorial))
          + "  show_ui=" + string(show_ui);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "bridge ready=" + string(qqm_ready) + " logged=" + string(qqm_logged)
          + " ffmpeg=" + string(qqm_ffmpeg) + " req=" + string(qqm_req)
          + " kind=" + qqm_kind;
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "demo step=" + string(qqm_demo_step) + " tries=" + string(qqm_demo_tries)
          + " pick=" + string(qqm_demo_pick) + " dead=" + string(array_length(qqm_dead))
          + " vip0=" + string(array_length(qqm_tracks) > 0 && variable_struct_exists(qqm_tracks[0], "vip") ? qqm_tracks[0].vip : -9);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "playlists=" + string(array_length(qqm_playlists))
          + " tracks=" + string(array_length(qqm_tracks)) + " view=" + string(qqm_view);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "sound=" + string(qqm_sound) + " state=" + qqm_play_state
          + " alive=" + string(qqm_sound != -1 ? audio_is_playing(qqm_sound) : 0);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "title=" + qqm_clip(qqm_play_title) + "  status=" + qqm_clip(qqm_status);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    _line = "file=" + qqm_clip(qqm_play_file);
    draw_text_transformed(_x, _y + (_i * 20), _line, 0.3, 0.3, 0); _i += 1;
    if (qqm_err_count > 0)
    {
        draw_set_color(c_red);
        draw_text_transformed(_x, _y + (_i * 20),
            "ERR[" + string(qqm_err_count) + "] " + qqm_clip(qqm_err), 0.3, 0.3, 0);
        draw_set_color(c_white);
        _i += 1;
    }
    draw_set_color(c_white);
    draw_set_alpha(1);
    draw_set_halign(fa_center);
}

/// @description Index of a playable track: not VIP, not already known dead.
function qqm_demo_free_track()
{
    var _n = array_length(qqm_tracks);
    if (_n == 0)
    {
        return 0;
    }
    var _best = -1;
    for (var k = 0; k < _n; k++)
    {
        var _i = (k + qqm_demo_tries) % _n;
        var _t = qqm_tracks[_i];
        if (array_contains(qqm_dead, string(_t.id)))
        {
            continue;
        }
        var _vip = 0;
        if (variable_struct_exists(_t, "vip"))
        {
            _vip = _t.vip;
        }
        if (_vip == 0)
        {
            return _i;
        }
        if (_best < 0)
        {
            _best = _i;
        }
    }
    if (_best >= 0)
    {
        return _best;
    }
    return qqm_demo_tries % _n;
}

/// @description Scripted first-run self test: open panel, search, play a free track.
function qqm_demo_drive()
{
    if (qqm_demo_timer > 0)
    {
        qqm_demo_timer -= 1;
        return;
    }
    switch (qqm_demo_step)
    {
        case 0:
            page_music_list = 1;
            qqm_open = 1;
            qqm_demo_step = 1;
            break;
        case 1:
            if (qqm_get("/status", "status") == 1)
            {
                qqm_demo_step = 2;
            }
            break;
        case 2:
            if (qqm_req == -1)
            {
                qqm_demo_step = 3;
            }
            break;
        case 3:
            if (qqm_get("/search?q=" + qqm_urlenc("Lo-fi") + "&n=30", "search") == 1)
            {
                qqm_demo_step = 4;
            }
            break;
        case 4:
            if (qqm_req == -1)
            {
                if (array_length(qqm_tracks) > 0)
                {
                    qqm_demo_pick = qqm_demo_free_track();
                    qqm_play_at(qqm_demo_pick);
                    qqm_demo_wait = 0;
                    qqm_demo_step = 5;
                }
                else
                {
                    qqm_demo_finish();
                }
            }
            break;
        case 5:
            qqm_demo_wait += 1;
            if (qqm_sound != -1 && audio_is_playing(qqm_sound))
            {
                qqm_demo_step = 6;
            }
            else if (qqm_demo_wait > 1500)
            {
                qqm_demo_tries += 1;
                qqm_demo_wait = 0;
                if (qqm_demo_tries >= 6)
                {
                    qqm_demo_finish();
                }
                else
                {
                    qqm_demo_pick = qqm_demo_free_track();
                    qqm_play_at(qqm_demo_pick);
                }
            }
            break;
        case 6:
            qqm_demo_step = 7;
            break;
    }
}

/// @description Draw wrapper: catch errors and always render the HUD.
function qqm_draw()
{
    try
    {
        qqm_draw_body();
    }
    catch (_e)
    {
        qqm_err = "draw: " + string(_e.message) + " L" + string(_e.line);
        qqm_err_count += 1;
    }
    if (qqm_hud == 1)
    {
        try
        {
            qqm_test_hud();
        }
        catch (_e2)
        {
            qqm_err = "hud: " + string(_e2.message);
        }
    }
}

/// @description The 本地音乐 / QQ音乐 tab row, drawn in BOTH modes so the QQ
/// page stays reachable after switching back to the cassette list.
function qqm_draw_tabs()
{
    draw_set_font(fontCJK);
    draw_set_valign(fa_middle);
    draw_set_halign(fa_center);
    draw_set_alpha(1);

    // ---- 本地音乐 ----
    if (button_collision(35, 365, 115, 389))
    {
        draw_set_alpha(0.25);
        draw_roundrect(35, 365, 115, 389, false);
        draw_set_alpha(1);
        if (button_click(35, 365, 115, 389))
        {
            qqm_open = 0;
            qqm_search_focus = 0;
            keyboard_string = "";
        }
    }
    else if (qqm_open == 0)
    {
        draw_set_alpha(0.35);
        draw_roundrect(35, 365, 115, 389, false);
        draw_set_alpha(1);
    }
    draw_set_color(c_white);
    draw_text_transformed(75, 379, qqm_text("tab_local"), 0.3, 0.3, 0);

    // ---- QQ音乐 ----
    if (button_collision(119, 365, 219, 389))
    {
        draw_set_alpha(0.25);
        draw_roundrect(119, 365, 219, 389, false);
        draw_set_alpha(1);
        if (button_click(119, 365, 219, 389))
        {
            qqm_open = 1;
            if (qqm_ready == 0)
            {
                qqm_status = qqm_text("loading");
                qqm_get("/status", "status");
            }
        }
    }
    else if (qqm_open == 1)
    {
        draw_set_alpha(0.35);
        draw_roundrect(119, 365, 219, 389, false);
        draw_set_alpha(1);
    }
    draw_text_transformed(169, 379, qqm_text("tab_qq"), 0.3, 0.3, 0);

    // ---- bridge / login hint at the right of the tab row ----
    draw_set_halign(fa_right);
    if (qqm_ready == -1)
    {
        draw_set_color(c_red);
        draw_text_transformed(392, 379, qqm_text("offline"), 0.22, 0.22, 0);
        draw_set_color(c_white);
    }
    else if (qqm_logged == 0 && qqm_view != 0 && qqm_saw_status == 1)
    {
        draw_set_alpha(0.7);
        draw_text_transformed(392, 379, qqm_text("nologin"), 0.22, 0.22, 0);
        draw_set_alpha(1);
    }
    draw_set_halign(fa_center);
    draw_set_color(c_white);
    draw_set_alpha(1);
}

/// @description Draw the QQ Music panel inside the game's music list window.
function qqm_draw_body()
{
    if (page_music_list != 1)
    {
        return;
    }
    var _sub_y1 = 392;
    var _sub_y2 = 413;
    var _row_y0 = 415;

    if (qqm_open == 0)
    {
        // the game draws its own cassette panel; just add the tab row so the
        // QQ page remains reachable
        qqm_draw_tabs();
        return;
    }

    draw_set_alpha(0.7);
    draw_set_color(c_black);
    draw_roundrect(25, 360, 460, 640, false);
    draw_set_alpha(1);
    draw_set_color(c_white);
    draw_set_font(fontCJK);
    draw_set_valign(fa_middle);
    draw_set_halign(fa_center);
    draw_set_alpha(1);

    qqm_draw_tabs();

    // ---------------- close button ----------------
    draw_sprite_ext(spr_icon_close_small, 0, 460, 370, 1, 1, 0, c_white, 1);
    if (button_click(446, 356, 474, 384))
    {
        page_music_list = -1;
        qqm_search_focus = 0;
        keyboard_string = "";
    }

    // ---------------- sub row: views / search box ----------------
    if (qqm_view == 2)
    {
        draw_set_alpha(0.3);
        draw_roundrect(35, _sub_y1, 320, _sub_y2, false);
        draw_set_alpha(1);
        draw_set_halign(fa_left);
        var _shown = qqm_query;
        if (_shown == "" && qqm_search_focus == 0)
        {
            _shown = qqm_text("hint");
            draw_set_alpha(0.55);
        }
        draw_text_transformed(42, 402, _shown, 0.28, 0.28, 0);
        draw_set_alpha(1);
        if (qqm_search_focus == 1)
        {
            qqm_caret = (qqm_caret + 1) % 60;
            if (qqm_caret < 30)
            {
                draw_sprite_ext(spr_typing_flash, 0, 42 + (string_width(_shown) * 0.28), 402,
                                0.7, 0.7, 0, c_white, 1);
            }
        }
        else if (button_click(35, _sub_y1, 320, _sub_y2))
        {
            qqm_search_focus = 1;
            keyboard_string = qqm_query;
        }
        draw_set_halign(fa_center);

        if (button_collision(326, _sub_y1, 386, _sub_y2))
        {
            draw_set_alpha(0.35);
            draw_roundrect(326, _sub_y1, 386, _sub_y2, false);
            draw_set_alpha(1);
            if (button_click(326, _sub_y1, 386, _sub_y2) && string_length(qqm_query) > 0)
            {
                qqm_scroll = 0;
                qqm_loading = 1;
                qqm_status = qqm_text("loading");
                qqm_get("/search?q=" + qqm_urlenc(qqm_query) + "&n=30", "search");
            }
        }
        else
        {
            draw_set_alpha(0.2);
            draw_roundrect(326, _sub_y1, 386, _sub_y2, false);
            draw_set_alpha(1);
        }
        draw_text_transformed(356, 402, qqm_text("search"), 0.28, 0.28, 0);

        if (button_collision(392, _sub_y1, 420, _sub_y2))
        {
            draw_set_alpha(0.3);
            draw_roundrect(392, _sub_y1, 420, _sub_y2, false);
            draw_set_alpha(1);
        }
        else
        {
            draw_set_alpha(0.15);
            draw_roundrect(392, _sub_y1, 420, _sub_y2, false);
            draw_set_alpha(1);
        }
        draw_text_transformed(406, 402, "<<", 0.24, 0.24, 0);
        if (button_click(392, _sub_y1, 420, _sub_y2))
        {
            qqm_view = 0;
            qqm_scroll = 0;
            qqm_search_focus = 0;
            keyboard_string = "";
        }
    }
    else
    {
        if (button_collision(35, _sub_y1, 95, _sub_y2))
        {
            draw_set_alpha(0.35);
            draw_roundrect(35, _sub_y1, 95, _sub_y2, false);
            draw_set_alpha(1);
            if (button_click(35, _sub_y1, 95, _sub_y2))
            {
                qqm_view = 0;
                qqm_scroll = 0;
                if (array_length(qqm_playlists) == 0)
                {
                    qqm_status = qqm_text("loading");
                    qqm_get("/playlists", "playlists");
                }
            }
        }
        else
        {
            draw_set_alpha(qqm_view == 0 ? 0.3 : 0.15);
            draw_roundrect(35, _sub_y1, 95, _sub_y2, false);
            draw_set_alpha(1);
        }
        draw_text_transformed(65, 402, qqm_text("playlist"), 0.28, 0.28, 0);

        if (button_collision(99, _sub_y1, 159, _sub_y2))
        {
            draw_set_alpha(0.35);
            draw_roundrect(99, _sub_y1, 159, _sub_y2, false);
            draw_set_alpha(1);
        }
        else
        {
            draw_set_alpha(0.15);
            draw_roundrect(99, _sub_y1, 159, _sub_y2, false);
            draw_set_alpha(1);
        }
        draw_text_transformed(129, 402, qqm_text("search"), 0.28, 0.28, 0);

        if (button_click(99, _sub_y1, 159, _sub_y2))
        {
            qqm_view = 2;
            qqm_scroll = 0;
            qqm_search_focus = 1;
            keyboard_string = qqm_query;
        }

        // ---- 队列 (now playing / play queue) ----
        if (button_collision(163, _sub_y1, 223, _sub_y2))
        {
            draw_set_alpha(0.35);
            draw_roundrect(163, _sub_y1, 223, _sub_y2, false);
            draw_set_alpha(1);
        }
        else
        {
            draw_set_alpha(qqm_view == 3 ? 0.3 : 0.15);
            draw_roundrect(163, _sub_y1, 223, _sub_y2, false);
            draw_set_alpha(1);
        }
        draw_text_transformed(193, 402, qqm_text("queue"), 0.28, 0.28, 0);
        if (button_click(163, _sub_y1, 223, _sub_y2))
        {
            qqm_view = 3;
            var _qn = array_length(qqm_queue);
            if (_qn > 0 && qqm_play_index >= 0)
            {
                qqm_scroll = clamp(qqm_play_index - 2, 0, max(0, _qn - qqm_rows));
            }
            else
            {
                qqm_scroll = 0;
            }
        }

        // status / list name
        draw_set_halign(fa_left);
        draw_set_alpha(0.8);
        var _info = qqm_status;
        if (_info == "" && qqm_view == 3)
        {
            _info = qqm_queue_name + " (" + string(array_length(qqm_queue)) + ")";
        }
        if (_info == "" && qqm_view == 1 && qqm_pl_name != "")
        {
            _info = qqm_pl_name;
        }
        if (_info != "")
        {
            draw_text_transformed(230, 402, string_copy(_info, 1, 26), 0.22, 0.22, 0);
        }
        draw_set_alpha(1);
        draw_set_halign(fa_center);
    }

    // ---------------- rows ----------------
    var _list = qqm_playlists;
    if (qqm_view == 3)
    {
        _list = qqm_queue;
    }
    else if (qqm_view != 0)
    {
        _list = qqm_tracks;
    }
    var _total = array_length(_list);
    var _maxscroll = max(0, _total - qqm_rows);
    qqm_hovered = -1;   // rebuilt every frame by the row loop below

    if (button_collision(30, 415, 410, 625) && _maxscroll > 0)
    {
        if (mouse_wheel_down())
        {
            qqm_scroll = min(qqm_scroll + 1, _maxscroll);
        }
        if (mouse_wheel_up())
        {
            qqm_scroll = max(qqm_scroll - 1, 0);
        }
    }
    qqm_scroll = clamp(qqm_scroll, 0, _maxscroll);

    if (_total == 0)
    {
        draw_set_halign(fa_left);
        draw_set_alpha(0.6);
        var _empty = qqm_text("empty");
        if (qqm_view == 3)
        {
            _empty = qqm_text("queue_empty");
        }
        draw_text_transformed(40, 430, _empty, 0.3, 0.3, 0);
        draw_set_alpha(1);
        draw_set_halign(fa_center);
    }

    for (var i = 0; i < min(_total, qqm_rows); i++)
    {
        var _idx = i + qqm_scroll;
        var _ry1 = _row_y0 + (i * 35);
        var _ry2 = _ry1 + 30;
        var _hover = button_collision(35, _ry1, 400, _ry2);
        // match on the song id so the "now playing" marker follows the music
        // in every view, whatever the queue happens to be
        var _playing = (qqm_play_id != "" && string(_list[_idx].id) == qqm_play_id
                        && (qqm_sound != -1 || qqm_play_state != ""));
        if (_hover)
        {
            qqm_hovered = _idx;
        }

        if (_hover || _playing)
        {
            draw_set_alpha(_hover ? 0.3 : 0.18);
            draw_roundrect(35, _ry1, 400, _ry2, false);
            draw_set_alpha(1);
        }

        draw_set_halign(fa_left);
        draw_set_valign(fa_middle);
        var _label = "";
        var _color = c_white;
        if (qqm_view == 0)
        {
            var _p = _list[_idx];
            _label = string(_p.name);
            if (variable_struct_exists(_p, "count"))
            {
                _label += "  (" + string(_p.count) + ")";
            }
            if (variable_struct_exists(_p, "special") && _p.special == "fav")
            {
                _label = "♥ " + _label;
            }
            _color = c_white;
        }
        else
        {
            var _t = _list[_idx];
            _label = string(_t.name);
            if (variable_struct_exists(_t, "singer") && string(_t.singer) != "")
            {
                _label += " - " + string(_t.singer);
            }
            if (variable_struct_exists(_t, "vip") && _t.vip == 1)
            {
                _color = 10079487;
            }
            if (_playing)
            {
                _color = 65535;
            }
        }
        draw_set_color(_color);
        if (qqm_view == 3)
        {
            // leave room for the ▲ ▼ × controls on the right
            draw_text_transformed(40, _ry1 + 15, string_copy(_label, 1, 30), 0.3, 0.3, 0);
        }
        else
        {
            draw_text_transformed(40, _ry1 + 15, qqm_clip(_label), 0.3, 0.3, 0);
        }
        draw_set_color(c_white);

        // ---- queue editing controls (queue view only) ----
        var _btn = 0;
        if (qqm_view == 3)
        {
            var _cy = _ry1 + 15;
            if (button_collision(302, _ry1, 324, _ry2))
            {
                _btn = 1;
            }
            else if (button_collision(326, _ry1, 348, _ry2))
            {
                _btn = 2;
            }
            else if (button_collision(354, _ry1, 376, _ry2))
            {
                _btn = 3;
            }
            draw_set_alpha(_btn == 1 ? 1.0 : 0.55);
            draw_triangle(313, _cy - 5, 307, _cy + 4, 319, _cy + 4, false);
            draw_set_alpha(_btn == 2 ? 1.0 : 0.55);
            draw_triangle(337, _cy + 5, 331, _cy - 4, 343, _cy - 4, false);
            draw_set_alpha(_btn == 3 ? 1.0 : 0.55);
            draw_line_width(360, _cy - 5, 370, _cy + 5, 2);
            draw_line_width(370, _cy - 5, 360, _cy + 5, 2);
            draw_set_alpha(1);
        }

        if (_hover && mouse_check_button_pressed(mb_left))
        {
            if (_btn == 1)
            {
                qqm_queue_move(_idx, _idx - 1);
                break;   // the array just changed; redraw next frame
            }
            if (_btn == 2)
            {
                qqm_queue_move(_idx, _idx + 1);
                break;
            }
            if (_btn == 3)
            {
                qqm_queue_remove(_idx);
                break;
            }
            if (qqm_view == 0)
            {
                qqm_pl_name = string(_list[_idx].name);
                qqm_pl_id = string(_list[_idx].id);
                qqm_status = qqm_text("loading");
                qqm_get("/playlist?id=" + qqm_urlenc(qqm_pl_id) + "&count=500", "playlist");
            }
            else if (qqm_view == 3)
            {
                qqm_play_from_queue(_idx);
            }
            else
            {
                qqm_play_at(_idx);
            }
        }
    }

    // ---------------- scrollbar ----------------
    if (_total > qqm_rows)
    {
        draw_set_alpha(0.5);
        draw_line_width(425, 425, 425, 625, 2);
        draw_set_alpha(1);
        var _sy = 425 + ((qqm_scroll / _maxscroll) * 200);
        draw_circle(425, _sy, 5, false);
    }

    // ---------------- now playing footer ----------------
    draw_set_halign(fa_left);
    if (qqm_play_title != "")
    {
        draw_set_alpha(0.85);
        draw_text_transformed(35, 631, qqm_clip("♪ " + qqm_bar_title()), 0.24, 0.24, 0);
        draw_set_alpha(1);
    }
    draw_set_halign(fa_center);
    draw_set_color(c_white);
    draw_set_alpha(1);
}
