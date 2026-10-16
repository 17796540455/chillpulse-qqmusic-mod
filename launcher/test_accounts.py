import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("accounts", Path(__file__).with_name("accounts.py"))
accounts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accounts)


class AccountTests(unittest.TestCase):
    def test_qq_cookie_and_wechat_account(self):
        self.assertEqual(accounts.parse_cookie("Cookie: uin=o123; qm_keyst=test", "qq")["uin"], "123")
        self.assertEqual(accounts.parse_cookie("wxuin=456; qqmusic_key=test", "qq")["uin"], "456")

    def test_wrong_platform_and_entire_headers_rejected(self):
        for text, source in (("MUSIC_U=test", "qq"), ("uin=123; qm_keyst=test", "netease"),
                             ("MUSIC_U=test\r\nHost: music.163.com", "netease")):
            with self.assertRaises(accounts.LoginError):
                accounts.parse_cookie(text, source)

    def test_failed_validation_does_not_replace_existing_account(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "auth_netease.json"
            path.write_text('{"cookie":"MUSIC_U=previous"}', encoding="utf-8")
            with patch.object(accounts, "fetch_json", return_value={"code": 200, "profile": None}):
                with self.assertRaises(accounts.LoginError):
                    accounts.save_login("MUSIC_U=expired", "netease", folder)
            self.assertEqual(json.loads(path.read_text())["cookie"], "MUSIC_U=previous")

    def test_two_accounts_are_saved_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(accounts, "fetch_json", return_value={"code": 200, "profile": {"userId": 42, "nickname": "test"}}):
                self.assertIn("test", accounts.save_login("MUSIC_U=test", "netease", folder))
            with patch.object(accounts, "fetch_json", return_value={"code": 0, "req_0": {"code": 0, "data": {"v_playlist": []}}}):
                accounts.save_login("uin=123; qm_keyst=test", "qq", folder)
            self.assertEqual(json.loads((Path(folder) / "auth_netease.json").read_text())["cookie"], "MUSIC_U=test")
            self.assertEqual(json.loads((Path(folder) / "auth.json").read_text())["uin"], "123")
            self.assertEqual(len(list(Path(folder).iterdir())), 2)

    def test_qq_rejected_response_not_treated_as_success(self):
        with patch.object(accounts, "fetch_json", return_value={"code": 0, "req_0": {"code": 1000}}):
            with self.assertRaises(accounts.LoginError):
                accounts.validate({"uin": "123", "cookie": "qm_keyst=test"}, "qq")


if __name__ == "__main__":
    unittest.main()
