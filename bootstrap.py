"""Windows 離線啟動：以內附 Python 檢查及展開固定版本 Pygame。"""
from pathlib import Path, PurePosixPath
import hashlib
import os
import stat
import subprocess
import sys
import zipfile

BUNDLE = 'pygame-ce-2.5.6-windows-py312.zip'
BUNDLE_SHA256 = '44522fa284eb19fa7290897b0724a89f194d96f88291f19c2750d48bbf27a36d'
PYGAME_VERSION = '2.5.6'


def pygame_ready(root):
    python = root / 'runtime/python.exe'
    probe = subprocess.run(
        [str(python), '-c',
         "import sys;sys.path.insert(0,sys.argv[1]);import pygame;"
         "assert pygame.IS_CE and pygame.version.ver==sys.argv[2]",
         str(root / '.vendor'), PYGAME_VERSION],
        capture_output=True, timeout=30,
        env=dict(os.environ, PYGAME_HIDE_SUPPORT_PROMPT='1'))
    return probe.returncode == 0


def install_bundle(root):
    root = Path(root).resolve()
    bundle = root / 'dependencies' / BUNDLE
    if not bundle.is_file():
        raise RuntimeError('缺少離線 Pygame 安裝包，請重新下載並完整解壓縮專案。')
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != BUNDLE_SHA256:
        raise RuntimeError('Pygame 安裝包不完整，請重新下載專案。')
    target = root / '.vendor'
    if not target.resolve().is_relative_to(root):
        raise RuntimeError('Pygame 安裝位置必須位於專案資料夾內。')
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if (not parts or parts[0] not in ('pygame', 'pygame_ce-2.5.6.dist-info')
                    or '..' in parts or '\\' in info.filename or ':' in info.filename
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or not (target / info.filename).resolve().is_relative_to(target.resolve())):
                raise RuntimeError('Pygame 安裝包包含無效路徑。')
        archive.extractall(target)


def ensure_dependencies(root):
    root = Path(root).resolve()
    if pygame_ready(root):
        return
    print('首次啟動：正在安裝內附 Pygame，不需要網路，請稍候……', flush=True)
    install_bundle(root)
    if not pygame_ready(root):
        raise RuntimeError('Pygame 無法載入。請確認使用 Windows 64 位元，並完整解壓縮專案。')
    print('Pygame 準備完成，正在啟動遊戲。', flush=True)


def main():
    root = Path(__file__).resolve().parent
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        print('此雙擊啟動方式需要內附的 Windows 64 位元 Python 3.12。')
        return 1
    try:
        ensure_dependencies(root)
        return subprocess.call([str(root / 'runtime/python.exe'), str(root / 'main.py'), *sys.argv[1:]], cwd=root)
    except (OSError, RuntimeError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        print(f'啟動失敗：{error}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
