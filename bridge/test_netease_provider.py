from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import netease as ne
from providers._aes import encrypt


class ProviderTests(unittest.TestCase):
    def resolve(self, data):
        with patch.object(ne, "_playback_api", return_value={"code":200,"data":[data]}):
            return ne.song_url_ex("21785756")

    def test_windows_aes_matches_nist_vector(self):
        data=bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
        key=bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        encrypted=encrypt(data,key)
        self.assertEqual(encrypted[:16].hex(),"3ad77bb40d7a3660a89ecaf32466ef97")
        self.assertEqual(len(encrypted),32)  # PKCS#7 adds a complete padding block.

    def test_complete_playback_is_returned(self):
        result=self.resolve({"url":"https://m801.music.126.net/example.mp3","code":200})
        self.assertTrue(result["url"])

    def test_trial_url_does_not_masquerade_as_full_track(self):
        with self.assertRaisesRegex(ne.BridgeError,"试听"):
            self.resolve({"url":"https://m801.music.126.net/trial.mp3","code":200,
                          "freeTrialInfo":{"start":0,"end":30}})

    def test_url_with_error_code_is_not_published(self):
        with self.assertRaises(ne.BridgeError):
            self.resolve({"url":"https://m801.music.126.net/example.mp3","code":-110})

    def test_logged_in_error_does_not_claim_membership_or_delisting(self):
        with patch.object(ne,"_cookie",return_value="MUSIC_U=private"):
            with self.assertRaisesRegex(ne.BridgeError,"播放权限") as caught:
                self.resolve({"code":-110})
            self.assertNotIn("已下架",str(caught.exception))

    def test_missing_login_has_explicit_error(self):
        with patch.object(ne,"_cookie",return_value=""):
            with self.assertRaisesRegex(ne.BridgeError,"网易云登录"):
                self.resolve({"code":-110})

    def test_invalid_id_is_rejected_without_network(self):
        with patch.object(ne,"_playback_api") as call:
            with self.assertRaisesRegex(ne.BridgeError,"ID"):
                ne.song_url_ex("ne:not-an-id")
            call.assert_not_called()

    def test_eapi_request_is_post_and_keeps_credentials_on_official_host(self):
        seen=[]
        class Reply:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"code":200,"data":[]}'
        class Opener:
            def open(self,request,timeout):
                seen.append(request)
                return Reply()
        with patch.object(ne,"_opener",return_value=Opener()), patch.object(ne,"_cookie",return_value="MUSIC_U=private; os=android; appver=old"):
            ne._playback_api({"ids":"[21785756]","level":"standard","encodeType":"flac"})
        request=seen[0]
        self.assertEqual(request.get_method(),"POST")
        self.assertEqual(request.host,"interface3.music.163.com")
        self.assertTrue(request.data.startswith(b"params="))
        self.assertNotIn(b"private",request.data)
        self.assertIn("MUSIC_U=private",request.get_header("Cookie"))
        self.assertNotIn("android",request.get_header("Cookie"))


unittest.main(verbosity=2)
