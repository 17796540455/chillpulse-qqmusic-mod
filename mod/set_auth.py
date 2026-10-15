"""Write QQ Music credentials from a pasted Cookie header into the bridge's
auth.json, then verify that VIP playback actually works.

Usage:
    python set_auth.py "uin=...; qm_keyst=...; ..."
    python set_auth.py            (reads the cookie blob from stdin)
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

AUTH = r"E:\steam\steam\steamapps\common\ChillPulse\QQMusicMod\auth.json"
BASE = "http://127.0.0.1:38610"

# Fields that must be present for playback; everything else is passed through
# so we never drop something the bridge might need.
REQUIRED_ANY = ["qm_keyst", "qqmusic_key", "qqmusic_keyst", "qm_keyst_new"]
DROP = {"ptcz", "RK", "pgv_pvid", "pgv_info", "ts_last", "ts_uid", "yyb_muid",
        "wxopenid", "wxrefresh_token", "wxunionid", "psrf_access_token_expiresAt",
        "psrf_musickey_createtime", "euin"}
KEEP_ALWAYS = {"uin", "wxuin", "login_type", "tmeLoginType", "qlogin_uid"}


def get(path, timeout=150):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_cookie(blob):
    blob = blob.strip()
    blob = re.sub(r"^\s*cookie\s*:\s*", "", blob, flags=re.I)
    blob = blob.strip().strip('"').strip("'")
    out = {}
    for part in blob.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def main():
    blob = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    if not blob.strip():
        print("!! no cookie text given")
        return 1

    cookies = parse_cookie(blob)
    print(f"parsed {len(cookies)} cookie fields")
    keep = {k: v for k, v in cookies.items()
            if v and (k in KEEP_ALWAYS or k not in DROP)}
    for k, v in sorted(keep.items()):
        shown = v if k in ("uin", "login_type", "tmeLoginType", "qlogin_uid") else v[:8] + "..." + f"({len(v)})"
        print(f"   {k} = {shown}")
    if not any(keep.get(k) for k in REQUIRED_ANY):
        print("!! none of qm_keyst / qqmusic_key found - that is the login ticket; "
              "copy the Cookie header while logged in at y.qq.com")
        return 1
    if not (keep.get("uin") or keep.get("wxuin")):
        print("!! uin / wxuin not found")

    uin = keep.get("uin") or keep.get("wxuin") or "0"
    uin = re.sub(r"\D", "", uin) or "0"
    cookie = "; ".join(f"{k}={v}" for k, v in keep.items())
    os.makedirs(os.path.dirname(AUTH), exist_ok=True)
    with open(AUTH, "w", encoding="utf-8") as f:
        json.dump({"uin": uin, "cookie": cookie}, f, ensure_ascii=False, indent=1)
    print(f"wrote {AUTH} (uin={uin}, {len(cookie)} chars of cookie)")

    print("waiting for the bridge to pick it up ...")
    time.sleep(4)
    st = get("/status")
    print("status:", json.dumps(st, ensure_ascii=False))
    if not st.get("logged_in"):
        print("!! bridge still reports logged_in=false - check the log")
        return 1

    # --- the real question: can this account play a VIP track? --------------
    for kw in ("周杰伦 晴天", "周杰伦"):
        hits = (get("/search?q=" + urllib.parse.quote(kw) + "&n=10").get("tracks") or [])
        vip = [t for t in hits if t.get("vip")]
        print(f"search {kw!r}: {len(hits)} hits, {len(vip)} VIP")
        for t in (vip or hits)[:3]:
            r = get("/play?id=" + t["id"] + "&name=" + urllib.parse.quote(t["name"]))
            state = r.get("state")
            if state == "ready":
                print(f"   PLAYABLE  {t['name']} - {t['singer']}  -> {r.get('file')}")
                print("\nVIP PLAYBACK WORKS - 绿钻票据可用于播放")
                return 0
            if state == "preparing":
                for _ in range(40):
                    time.sleep(3)
                    s = get("/playstate?id=" + t["id"])
                    if s.get("state") == "ready":
                        print(f"   PLAYABLE  {t['name']} - {t['singer']} -> {s.get('file')}")
                        print("\nVIP PLAYBACK WORKS - 绿钻票据可用于播放")
                        return 0
                    if s.get("state") == "error":
                        print(f"   FAILED    {t['name']}: {s.get('msg')}")
                        break
            else:
                print(f"   FAILED    {t['name']}: {r.get('msg')}")
    print("\n!! VIP tracks still refused - the web ticket is not enough for VIP "
          "playback; use the Phone-QQ QR login instead")
    return 2


if __name__ == "__main__":
    sys.exit(main())
