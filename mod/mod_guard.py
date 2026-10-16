"""Keep the patched data.win in place.

Steam restores `data.win` to the vanilla build whenever it verifies the game
files or downloads an update, which silently removes the QQ Music tab.  This
guard runs on every game launch (see bridge_launch.vbs) and puts the patched
file back, so a wipe repairs itself.

It is deliberately conservative: the file is only replaced when it is
byte-for-byte identical to the vanilla build this patch was made against.  Any
other content means the game was updated, and copying an old patched data.win
over a new build would break the game - so it is left completely alone and
reported instead.

Exit codes
    0   already patched, nothing to do
    10  the vanilla file was found and the patch was restored
    2   unknown data.win (game updated?) - left untouched, rebuild the patch
    3   data_patched.win is missing, cannot restore
    4   the game folder or data.win is missing
"""
import hashlib
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHED = os.path.join(HERE, "data_patched.win")
LOG = os.path.join(HERE, "mod_guard.log")
GAME_DIR_FILE = os.path.join(HERE, "game_dir.txt")
DEFAULT_GAME_DIR = r"E:\steam\steam\steamapps\common\ChillPulse"

VANILLA_SHA256 = "853f3a5bcbe37e43fd42e814dcf313021313f8ec1723c13c744dc7e78de95c7f"
PATCHED_SHA256 = "e3b1dede486de0ca7120e5dc55785a70db2afe1ae0ef30959374b3f4e04c4693"


def game_dir() -> str:
    """The game folder, overridable with game_dir.txt next to this script."""
    try:
        with open(GAME_DIR_FILE, "r", encoding="utf-8-sig") as fh:
            custom = fh.read().strip().strip('"')
        if custom:
            return custom
    except OSError:
        pass
    return DEFAULT_GAME_DIR


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    target = os.path.join(game_dir(), "data.win")

    if not os.path.isfile(target):
        log(f"ERROR  no data.win at {target} - is the game folder correct?")
        return 4
    if not os.path.isfile(PATCHED):
        log(f"ERROR  {PATCHED} is missing, cannot restore anything")
        return 3

    try:
        current = sha256(target)
    except OSError as exc:
        log(f"ERROR  cannot read {target}: {exc}")
        return 4

    if current == PATCHED_SHA256:
        log("ok     data.win is already patched")
        return 0

    if current != VANILLA_SHA256:
        log(f"WARN   data.win is neither the vanilla build this patch targets nor "
            f"the patched one (sha256 {current[:16]}...)")
        log("       the game has probably been updated - leaving it untouched.")
        log("       rebuild the patch for the new version before playing online.")
        return 2

    # vanilla -> restore, keeping a pristine copy for uninstalling
    backup = target + ".qqmod-backup"
    try:
        if not os.path.isfile(backup):
            shutil.copy2(target, backup)
            log(f"info   kept a pristine copy at {os.path.basename(backup)}")
        shutil.copy2(PATCHED, target)
        if sha256(target) != PATCHED_SHA256:
            log("ERROR  the restored file does not match the expected hash")
            return 3
    except OSError as exc:
        log(f"ERROR  could not restore data.win: {exc} (is the game running?)")
        return 3

    log("FIXED  Steam had restored the vanilla data.win - the patch is back")
    return 10


if __name__ == "__main__":
    sys.exit(main())



