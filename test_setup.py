import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import setup_mod


class SetupTests(unittest.TestCase):
    def test_updated_game_not_overwritten_from_old_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data.win").write_bytes(b"updated game")
            (root / "data.win.qqmod-backup").write_bytes(b"vanilla")
            expected = hashlib.sha256(b"vanilla").hexdigest()
            with self.assertRaises(RuntimeError):
                setup_mod.vanilla_file(root, expected)
            self.assertEqual((root / "data.win").read_bytes(), b"updated game")

    def test_reinstall_uses_verified_vanilla_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "mod").mkdir()
            (root / "data.win").write_bytes(b"patched")
            backup = root / "data.win.qqmod-backup"
            backup.write_bytes(b"vanilla")
            known = hashlib.sha256(b"patched").hexdigest()
            (root / "mod/mod_guard.py").write_text('PATCHED_SHA256 = "' + known + '"')
            with patch.object(setup_mod, "ROOT", root):
                self.assertEqual(setup_mod.vanilla_file(root, setup_mod.digest(backup)), backup)

    def test_deploy_rolls_back_previous_files_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / "new", root / "current"
            source.write_text("new")
            target.write_text("old")
            with self.assertRaises(FileNotFoundError):
                setup_mod.deploy([(source, target), (root / "missing", root / "other")], root / "backup")
            self.assertEqual(target.read_text(), "old")
            self.assertFalse((root / "other").exists())


if __name__ == "__main__":
    unittest.main()
