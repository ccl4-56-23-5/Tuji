"""Verify real packaged EXEs using synthetic data and isolated installation state."""
import hashlib
import json
import subprocess
import sys
import uuid
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
OUT = WORKSPACE / 'outputs/NefGpsTrack/1.5.2'
CACHE = WORKSPACE / 'temp/tuji-1.5.2/qa/windows-delivery'
sys.path.insert(0, str(ROOT / 'windows'))
from clp_codec import encrypt_clp, FIXED_KEY


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(executable, *args):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    result = subprocess.run([str(executable), *map(str, args)], startupinfo=startup,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=90)
    if result.returncode:
        raise RuntimeError(f'{executable.name}: exit {result.returncode}')


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    app = OUT / 'NefGpsTrack-Windows-1.5.2.exe'
    setup = OUT / 'NefGpsTrack-Setup-1.5.2.exe'
    fixture = json.loads((ROOT / 'qa/fixture.json').read_text(encoding='utf-8-sig'))
    clp = CACHE / 'synthetic-route.clp'
    clp.write_bytes(encrypt_clp(fixture, FIXED_KEY))
    data = CACHE / 'self-check-data'
    run(app, '--data-dir', data, '--self-check', OUT / 'windows-self-check.json')
    self_check = json.loads((OUT / 'windows-self-check.json').read_text(encoding='utf-8-sig'))
    assert self_check['ok'], self_check
    run(app, '--data-dir', data, '--ui-check', OUT / 'windows-ui-check.json', clp)
    ui_check = json.loads((OUT / 'windows-ui-check.json').read_text(encoding='utf-8-sig'))
    assert ui_check['ok'], ui_check

    run_id = uuid.uuid4().hex
    target = CACHE / run_id / '非默认安装目录' / '途记'
    shortcut = CACHE / run_id / 'test-only.lnk'
    reg_root = rf'Software\TujiDeliveryQA\{run_id}'
    try:
        run(setup, '--silent-install', target, '--no-migrate', '--reg-root', reg_root,
            '--shortcut', shortcut)
        installed = target / '途记.exe'
        assert digest(installed) == digest(app)
        route = target / 'data/路径库/合成测试路径.clp'
        prefs = target / 'data/程序数据/settings.json'
        route.write_bytes(clp.read_bytes())
        prefs.write_text(json.dumps({'defaultOffset': '+08:00', 'writeInPlace': False}), encoding='utf-8')
        before = {str(p.relative_to(target)): digest(p) for p in (route, prefs)}
        run(setup, '--silent-upgrade', '--no-migrate', '--reg-root', reg_root,
            '--shortcut', shortcut)
        after = {str(p.relative_to(target)): digest(p) for p in (route, prefs)}
        assert before == after
        assert digest(installed) == digest(app)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_root + r'\NefGpsTrack') as key:
            assert Path(winreg.QueryValueEx(key, 'InstallLocation')[0]) == target
            assert winreg.QueryValueEx(key, 'DisplayVersion')[0] == '1.5.2'
        result = {'ok': True, 'version': '1.5.2', 'firstInstallNonDefault': True,
                  'sameVersionUpgradeUsesRegisteredPath': True, 'dataHashesUnchanged': before,
                  'installedExeMatchesDeliverable': True, 'syntheticDataOnly': True,
                  'userInstallationModified': False, 'testDirectory': str(target),
                  'note': 'Tests packaged installation and reinstallation; no connected Android device.'}
        (OUT / 'windows-install-verification.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Packaged self-check, WebView2 bridge, isolated first install and upgrade: PASS')
    finally:
        # Only remove this run's uniquely named temporary registration.
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_root + r'\NefGpsTrack')
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_root)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
