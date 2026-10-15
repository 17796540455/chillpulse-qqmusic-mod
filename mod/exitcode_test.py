"""How does ChillPulse actually exit?  Read the process exit code.

Steam never clears its "running" flag for this game, so either the game exits
with a crash code (and Steam treats that as abnormal) or it exits cleanly and
Steam simply fails to notice.  The exit code settles it:

    0x00000000  clean ExitProcess
    0xC0000005  access violation (crash on shutdown)
    0xC0000409  stack buffer overrun / fail-fast
    0xC000013A  terminated by Ctrl+C / window close
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
import winreg

u = ctypes.windll.user32
k32 = ctypes.windll.kernel32
RUNNING_KEY = r"Software\Valve\Steam\Apps\2826180"
CODES = {0x0: "clean ExitProcess", 0xC0000005: "ACCESS VIOLATION (crash)",
         0xC0000409: "FAIL-FAST / stack overrun", 0xC000013A: "Ctrl+C / closed",
         0xC0000374: "heap corruption"}


def log(m):
    print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)


def procs():
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260)]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    out = []
    try:
        e = PE(); e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.szExeFile.decode("mbcs", "replace").lower()))
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def game_pid():
    for pid, name in procs():
        if name == "chillpulse.exe":
            return pid
    return None


def windows_of(pid):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _l):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 2)
            u.GetWindowTextW(h, b, n + 2)
            found.append((h, b.value))
        return True
    u.EnumWindows(cb, 0)
    return found


def main():
    log("launching the game via Steam")
    os.startfile("steam://rungameid/2826180")

    t0 = time.time()
    pid = None
    while time.time() - t0 < 120:
        pid = game_pid()
        if pid:
            break
        time.sleep(2)
    if not pid:
        log("ERROR the game never started"); return 2
    log(f"game pid {pid}")

    # handle it *before* it exits so the exit code can be read
    PROCESS_QUERY_LIMITED = 0x1000
    SYNCHRONIZE = 0x00100000
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED | SYNCHRONIZE, False, pid)
    if not h:
        log(f"ERROR OpenProcess failed ({ctypes.get_last_error()})"); return 2

    wins = []
    while time.time() - t0 < 150:
        wins = windows_of(pid)
        if wins:
            break
        time.sleep(3)
    log(f"windows: {wins}")
    time.sleep(10)

    for _ in range(5):
        wins = windows_of(pid)
        if not wins:
            break
        for hwnd, title in wins[:1]:
            log(f"WM_CLOSE -> {hwnd} {title!r}")
            u.PostMessageW(hwnd, 0x0010, 0, 0)
        time.sleep(6)

    log("waiting for the process to exit ...")
    k32.WaitForSingleObject(h, 120000)
    code = wt.DWORD()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    value = code.value
    log(f"EXIT CODE: 0x{value:08X}  ({CODES.get(value, 'unknown')})")

    time.sleep(15)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUNNING_KEY) as k:
            log(f"steam Running flag 15s later: {winreg.QueryValueEx(k, 'Running')[0]}")
    except OSError:
        pass
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
