"""Make the bridge's CDN Referer depend on which service the url belongs to.

QQ Music's CDN and NetEase's CDN both reject a request carrying the *other*
service's Referer - NetEase answers 403 Forbidden, which is what made every
NetEase download fail with 网络错误（HTTP 403）.
"""
import io
import os
import re
import sys

PATH = r"C:\Users\wmcyh\Documents\deepseek-harness\default-workspace\bridge\qqbridge.py"

HELPER = '''
def _cdn_referer(url: str) -> str:
    """The Referer the url's own CDN expects.

    Each service rejects a request that carries a foreign Referer: NetEase
    answers 403 Forbidden when it sees QQ Music's, which is why NetEase
    downloads failed while its url resolution worked.
    """
    host = urllib.parse.urlsplit(url or "").netloc.lower()
    if host.endswith("126.net") or "music.163.com" in host or host.endswith("163.com"):
        return "https://music.163.com/"
    return "https://y.qq.com/"


'''

src = io.open(PATH, encoding="utf-8").read()
original = src

if "_cdn_referer" in src:
    print("already patched")
    sys.exit(0)

# 1) insert the helper just before the cache-path helpers
anchor = "def out_path(mid: str) -> str:"
if anchor not in src:
    print("FAIL: anchor for the helper not found")
    sys.exit(1)
src = src.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

# 2) python download paths: two identical dict literals
before = src.count('"Referer": "https://y.qq.com/",')
src = src.replace('"Referer": "https://y.qq.com/",', '"Referer": _cdn_referer(url),')
print(f"python download headers patched: {before} site(s)")

# 3) ffmpeg url-in path
ff = '"-headers", "Referer: https://y.qq.com/\\r\\n",'
if ff in src:
    src = src.replace(ff, '"-headers", "Referer: " + _cdn_referer(url) + "\\r\\n",')
    print("ffmpeg url-in header patched: 1 site")
else:
    print("WARN: ffmpeg header line not found (check manually)")

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("written:", PATH, len(original), "->", len(src), "chars")

# syntax check with both interpreters
import py_compile
try:
    py_compile.compile(PATH, doraise=True)
    print("py_compile: OK")
except py_compile.PyCompileError as exc:
    print("py_compile FAILED:", exc)
    sys.exit(1)

left = len(re.findall(r'"Referer": "https://y\.qq\.com/"', src))
print("remaining hardcoded y.qq.com referers:", left, "(login endpoints are fine)")
