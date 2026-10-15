"""Windows process handles and per-session singleton locks for the mod."""
import ctypes as ct
from ctypes import wintypes as wt
import hashlib
import os

kernel = ct.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel.OpenProcess.restype = wt.HANDLE
kernel.CloseHandle.argtypes = [wt.HANDLE]
kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel.WaitForSingleObject.restype = wt.DWORD
kernel.CreateMutexW.argtypes = [ct.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel.CreateMutexW.restype = wt.HANDLE
kernel.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                            ct.POINTER(wt.DWORD)]


class ProcessEntry(ct.Structure):
    _fields_ = [("size", wt.DWORD), ("usage", wt.DWORD), ("pid", wt.DWORD),
                ("heap", ct.c_size_t), ("module", wt.DWORD),
                ("threads", wt.DWORD), ("parent", wt.DWORD),
                ("priority", wt.LONG), ("flags", wt.DWORD),
                ("name", wt.WCHAR * 260)]


kernel.Process32FirstW.argtypes = [wt.HANDLE, ct.POINTER(ProcessEntry)]
kernel.Process32NextW.argtypes = [wt.HANDLE, ct.POINTER(ProcessEntry)]


def close_handle(handle):
    if handle:
        kernel.CloseHandle(handle)


def acquire_singleton(kind, identity):
    key = hashlib.sha256(identity.lower().encode("utf-8")).hexdigest()[:24]
    handle = kernel.CreateMutexW(None, False, "Local\\ChillPulseQQ-" + kind + key)
    if not handle:
        raise ct.WinError(ct.get_last_error())
    if ct.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        close_handle(handle)
        return None
    return handle


def open_process(pid):
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        error = ct.get_last_error()
        if error == 87:  # process has already exited
            return None
        raise ct.WinError(error)
    return handle


def process_alive(handle):
    if not handle:
        return False
    result = kernel.WaitForSingleObject(handle, 0)
    if result == 0xFFFFFFFF:
        raise ct.WinError(ct.get_last_error())
    return result == 258


def wait_process(handle):
    result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
    if result == 0xFFFFFFFF:
        raise ct.WinError(ct.get_last_error())


def find_game(executable):
    """Return an open handle to the exact game executable, avoiding PID reuse."""
    executable = os.path.normcase(os.path.abspath(executable))
    snap = kernel.CreateToolhelp32Snapshot(2, 0)
    if snap == wt.HANDLE(-1).value:
        raise ct.WinError(ct.get_last_error())
    try:
        entry = ProcessEntry()
        entry.size = ct.sizeof(entry)
        ok = kernel.Process32FirstW(snap, ct.byref(entry))
        while ok:
            if entry.name.lower() == os.path.basename(executable).lower():
                handle = open_process(entry.pid)
                if handle:
                    buf = ct.create_unicode_buffer(32768)
                    length = wt.DWORD(len(buf))
                    if not kernel.QueryFullProcessImageNameW(handle, 0, buf,
                                                            ct.byref(length)):
                        error = ct.get_last_error()
                        close_handle(handle)
                        raise ct.WinError(error)
                    if os.path.normcase(buf.value) == executable:
                        return handle
                    close_handle(handle)
            ok = kernel.Process32NextW(snap, ct.byref(entry))
        return None
    finally:
        close_handle(snap)


def bridge_environment():
    """The helper must not advertise itself to Steam as the game."""
    game_keys = {"steamappid", "steamgameid", "steamoverlaygameid",
                 "steamgameservergameid", "steamclientlaunch"}
    return {key: value for key, value in os.environ.items()
            if key.lower() not in game_keys}
