"""Automated A/B test: does Steam get stuck when the game runs WITHOUT the mod?

Swaps in the vanilla data.win, launches the game from Steam, lets it load,
closes it with WM_CLOSE, and reports whether Steam cleared its running flag.
The patched data.win is restored afterwards either way.
"""
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import time
import winreg

GAME = r"E:\steam\steam\steamapps\common\ChillPulse"
DATA = os.path.join(GAME, "data.win")
VANILLA = os.path.join(GAME, "data.win.qqmod-backup")
PATCHED = r"E:\ChillPulseQQMod\data_patched.win"
RUNNING_KEY = r"Software\Valve\Steam\Apps\2826180"
u = ctypes.windll.user32


def running_flag():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUNNING_KEY) as k:
            return int(winreg.QueryValueEx(k, "Running")[0])
    except OSError:
        return None


def procs():
    TH32CS = 0x2

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260)]
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS, 0)
    names = set()
    try:
        e = PE(); e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            names.add(e.szExeFile.decode("mbcs", "replace").lower())
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return names


def game_windows():
    """Windows owned by ChillPulse.exe."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ChillPulse.exe", "/FO", "CSV"],
                         capture_output=True, text=True).stdout
    pids = set()
    for line in out.splitlines()[1:]:
        parts = line.split('","')
        if len(parts) > 1:
            try:
                pids.add(int(parts[1]))
            except ValueError:
                pass
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _l):
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids:
            n = u.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 2)
            u.GetWindowTextW(h, b, n + 2)
            found.append((h, bool(u.IsWindowVisible(h)), b.value))
        return True
    u.EnumWindows(cb, 0)
    return found


def log(m):
    print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)


def main():
    if not os.path.isfile(VANILLA):
        log("ERROR no vanilla backup"); return 2

    log(f"steam running flag: {running_flag()}")

    # ---- vanilla in place ------------------------------------------------
    shutil.copy2(VANILLA, DATA)
    log("swapped in the VANILLA data.win (mod disabled for this run)")

    try:
        # ---- launch from Steam -------------------------------------------
        os.startfile("steam://rungameid/2826180")
        log("asked Steam to launch the game")

        t0 = time.time()
        while time.time() - t0 < 120 and "chillpulse.exe" not in procs():
            time.sleep(2)
        if "chillpulse.exe" not in procs():
            log("ERROR the game never started"); return 2
        log(f"game process is up after {time.time()-t0:.0f}s")

        # wait for a *visible window*: the process alone is not enough, a
        # half-initialised launch exits again without ever showing one
        t0 = time.time()
        wins = []
        while time.time() - t0 < 150:
            if "chillpulse.exe" not in procs():
                log("game exited before showing a window - retrying the launch")
                time.sleep(10)
                os.startfile("steam://rungameid/2826180")
                t0 = time.time()
                continue
            wins = [w for w in game_windows() if w[1]]
            if wins:
                break
            time.sleep(3)
        if not wins:
            log("ERROR the game never showed a window; test inconclusive")
            return 2
        log(f"window is up after {time.time()-t0:.0f}s: {wins}")
        time.sleep(8)

        # ---- close it the polite way -------------------------------------
        for attempt in range(6):
            wins = [w for w in game_windows() if w[1]]
            if not wins:
                break
            for h, _v, title in wins[:2]:
                log(f"WM_CLOSE -> hwnd {h} {title!r}")
                u.PostMessageW(h, 0x0010, 0, 0)      # WM_CLOSE
            time.sleep(6)

        t0 = time.time()
        while time.time() - t0 < 90 and "chillpulse.exe" in procs():
            time.sleep(2)
        gone = "chillpulse.exe" not in procs()
        log(f"game process gone: {gone} (after {time.time()-t0:.0f}s)")
        if not gone:
            log("WARN could not close the game; test inconclusive"); return 2

        # ---- did Steam notice? -------------------------------------------
        time.sleep(20)
        flag = running_flag()
        log(f"steam running flag 20s after the game exited: {flag}")
        if flag == 0:
            log("RESULT  Steam cleared the flag -> the MOD is implicated")
        else:
            log("RESULT  Steam is STILL stuck -> NOT the mod's fault (game/Steam issue)")
        return 0
    finally:
        time.sleep(2)
        if os.path.isfile(PATCHED):
            shutil.copy2(PATCHED, DATA)
            log(f"restored the patched data.win ({os.path.getsize(DATA)} bytes)")


if __name__ == "__main__":
    sys.exit(main())
