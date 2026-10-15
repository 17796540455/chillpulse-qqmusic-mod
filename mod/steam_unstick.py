"""Clear a stale "game is running" record left behind in Steam.

Symptom: after quitting ChillPulse the Steam library still shows the button as
stopping / Stop, the Play button never comes back, and the save cannot sync
(`last_sync_state = changeslocally`).  Nothing is actually running at that
point - the game process is gone - Steam just never finished its shutdown
bookkeeping.  The only way out is to restart the Steam client.

This script detects exactly that state (Steam records the app as running while
no ChillPulse.exe exists) and restarts Steam.  bridge_launch.vbs calls it
before starting the game, so a stale record can never block a launch.

Exit codes
    0  nothing to do, Steam is in a sane state
    10 Steam was stuck and has been restarted
    2  could not restart Steam - do it by hand
"""
import ctypes
import os
import subprocess
import sys
import time
import winreg

APP_ID = "2826180"
GAME_EXE = "chillpulse.exe"
STEAM_EXE = r"E:\steam\steam\steam.exe"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_unstick.log")
RUNNING_KEY = rf"Software\Valve\Steam\Apps\{APP_ID}"


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def processes() -> set:
    """Names of running processes, via the toolhelp API (no pipes involved)."""
    TH32CS_SNAPPROCESS = 0x2
    MAX_PATH = 260

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * MAX_PATH)]

    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    names = set()
    if snap == -1:
        return names
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.decode("mbcs", "replace").lower())
            ok = k32.Process32Next(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return names


def steam_app_running():
    """1 / 0 / None (= unknown)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUNNING_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "Running")
            return int(value)
    except OSError:
        return None


def main() -> int:
    running = steam_app_running()
    game = GAME_EXE in processes()

    if game:
        log("ok     ChillPulse.exe is running - nothing to do")
        return 0
    if running != 1:
        log(f"ok     Steam does not think the game is running (Running={running})")
        return 0

    log("STUCK  Steam still records the game as running but no ChillPulse.exe "
        "exists -> restarting Steam")
    # NOTE: writing Running=0 in the registry is NOT enough - Steam's library
    # keeps showing "stopping" because the UI reads the client's in-memory
    # state.  Verified against a live stuck state: the flag cleared and the
    # button stayed on "stopping", so a real client restart is the only fix.

    try:
        os.startfile("steam://exit")
    except OSError as exc:
        log(f"ERROR  could not ask Steam to exit: {exc}")
        return 2

    deadline = time.time() + 60
    while time.time() < deadline and "steam.exe" in processes():
        time.sleep(1)
    if "steam.exe" in processes():
        log("ERROR  Steam did not exit within 60s")
        return 2
    log("info   steam.exe exited")

    try:
        subprocess.Popen([STEAM_EXE], close_fds=True)
    except OSError as exc:
        log(f"ERROR  could not start Steam: {exc}")
        return 2

    deadline = time.time() + 150
    while time.time() < deadline:
        time.sleep(3)
        if steam_app_running() != 1:
            log("FIXED  Steam is back and the stale record is gone")
            return 10
    log("WARN   Steam restarted but the record still says running")
    return 2


if __name__ == "__main__":
    sys.exit(main())
