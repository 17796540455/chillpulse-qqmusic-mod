"""AES-ECB with PKCS#7 padding via the Windows CNG API (no pip dependency)."""
import ctypes as c
from ctypes import wintypes as w


def encrypt(data: bytes, key: bytes) -> bytes:
    api = c.WinDLL("bcrypt")
    handle = c.c_void_p
    byteptr = c.c_void_p
    signatures = {
        "BCryptOpenAlgorithmProvider": [c.POINTER(handle), w.LPCWSTR, w.LPCWSTR, w.ULONG],
        "BCryptSetProperty": [handle,w.LPCWSTR,byteptr,w.ULONG,w.ULONG],
        "BCryptGetProperty": [handle,w.LPCWSTR,byteptr,w.ULONG,c.POINTER(w.ULONG),w.ULONG],
        "BCryptGenerateSymmetricKey": [handle,c.POINTER(handle),byteptr,w.ULONG,byteptr,w.ULONG,w.ULONG],
        "BCryptEncrypt": [handle,byteptr,w.ULONG,byteptr,byteptr,w.ULONG,byteptr,w.ULONG,c.POINTER(w.ULONG),w.ULONG],
        "BCryptDestroyKey": [handle],
        "BCryptCloseAlgorithmProvider": [handle,w.ULONG],
    }
    for name, signature in signatures.items():
        function = getattr(api,name)
        function.argtypes = signature
        function.restype = w.LONG

    def check(status):
        if status != 0:
            raise OSError("Windows AES operation failed: 0x%08X" % (status & 0xffffffff))

    algorithm, secret = handle(), handle()
    check(api.BCryptOpenAlgorithmProvider(c.byref(algorithm), "AES", None, 0))
    try:
        mode = c.create_unicode_buffer("ChainingModeECB")
        check(api.BCryptSetProperty(algorithm,"ChainingMode",mode,c.sizeof(mode),0))
        size, returned = w.ULONG(), w.ULONG()
        check(api.BCryptGetProperty(algorithm,"ObjectLength",c.byref(size),c.sizeof(size),c.byref(returned),0))
        key_object = c.create_string_buffer(size.value)
        key_bytes = c.create_string_buffer(key)
        check(api.BCryptGenerateSymmetricKey(algorithm,c.byref(secret),key_object,len(key_object),key_bytes,len(key),0))
        source = c.create_string_buffer(data)
        length = w.ULONG()
        check(api.BCryptEncrypt(secret,source,len(data),None,None,0,None,0,c.byref(length),1))
        result = c.create_string_buffer(length.value)
        check(api.BCryptEncrypt(secret,source,len(data),None,None,0,result,len(result),c.byref(length),1))
        return result.raw[:length.value]
    finally:
        if secret:
            api.BCryptDestroyKey(secret)
        api.BCryptCloseAlgorithmProvider(algorithm,0)
