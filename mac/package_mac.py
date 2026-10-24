"""Package the preverified Intel runtime. Run prepare_mac.py for a clean build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reuse-runtime',action='store_true',help='Reuse the bundled runtime from an existing local app')
    args=parser.parse_args()
    app=ROOT/'dist/RamPilot.app'
    contents=app/'Contents'
    resources=contents/'Resources'
    if not args.reuse_runtime:
        if not (ROOT/'mac/python/python/bin/python3.11').exists():
            raise SystemExit('Run python mac/prepare_mac.py first')
        if app.exists(): shutil.rmtree(app)
        resources.mkdir(parents=True)
        shutil.copytree(ROOT/'mac/python/python',resources/'python',symlinks=True)
        lock=json.loads((ROOT/'mac/runtime-lock.json').read_text())
        packages=resources/'python/lib/python3.11/site-packages'
        for item in lock['wheels']:
            wheel=ROOT/'mac/vendor/wheels'/item['file']
            with wheel.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=item['sha256']:
                    raise ValueError('Unverified wheel: '+wheel.name)
            with zipfile.ZipFile(wheel) as archive: archive.extractall(packages)
    elif not (resources/'python/bin/python3.11').exists():
        raise SystemExit('There is no existing runtime to reuse')
    appdata=resources/'app'
    if appdata.exists(): shutil.rmtree(appdata)
    appdata.mkdir(parents=True)
    for path in (ROOT/'mobile').glob('*.py'): shutil.copy2(path,appdata/path.name)
    for path in [ROOT/'mac/mac_ui.py',ROOT/'catalog.json']: shutil.copy2(path,appdata/path.name)
    for name in ['LICENSE.txt','THIRD-PARTY-NOTICES.txt','README.txt']: shutil.copy2(ROOT/name,resources/name)
    macos=contents/'MacOS'
    macos.mkdir(parents=True,exist_ok=True)
    launcher=macos/'RamPilot'
    launcher.write_text('''#!/bin/sh
APP_RES="$(CDPATH= cd -- "$(dirname -- "$0")/../Resources" && pwd)"
export OPENBLAS_NUM_THREADS=2
export OMP_NUM_THREADS=2
export PYTHONNOUSERSITE=1
unset PYTHONHOME PYTHONPATH
export TCL_LIBRARY="$APP_RES/python/lib/tcl8.6"
export TK_LIBRARY="$APP_RES/python/lib/tk8.6"
mkdir -p "$HOME/Library/Logs"
exec "$APP_RES/python/bin/python3" "$APP_RES/app/mac_ui.py" >> "$HOME/Library/Logs/RamPilot2.log" 2>&1
''')
    launcher.chmod(0o755)
    # A code-native icon is generated from the same app logo used by Windows.
    if (ROOT/'mac/RamPilot.icns').exists(): shutil.copy2(ROOT/'mac/RamPilot.icns',resources/'RamPilot.icns')
    info=dict(CFBundleName='RamPilot',CFBundleDisplayName='RamPilot',CFBundleIdentifier='com.rampilot.desktop',
              CFBundleVersion=VERSION,CFBundleShortVersionString=VERSION,CFBundleExecutable='RamPilot',
              CFBundlePackageType='APPL',LSMinimumSystemVersion='13.0',NSHighResolutionCapable=True)
    if (resources/'RamPilot.icns').exists(): info['CFBundleIconFile']='RamPilot.icns'
    with (contents/'Info.plist').open('wb') as stream: plistlib.dump(info,stream)
    output=ROOT/('dist/RamPilot-Mac-Ventura-Intel-'+VERSION+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,6) as archive:
        for path in sorted(app.rglob('*')):
            name=str(path.relative_to(app.parent))
            if path.is_symlink():
                entry=zipfile.ZipInfo(name);entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
                archive.writestr(entry,os.readlink(path))
            elif path.is_file(): archive.write(path,name)
        archive.write(ROOT/'PLATFORMS.md','READ-ME-FIRST.md')
    print(output,output.stat().st_size)


if __name__ == '__main__': main()
