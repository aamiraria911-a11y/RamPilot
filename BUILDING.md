# Build RamPilot 2.1

Build inputs are pinned by filename, publisher URL and SHA-256. Do not replace
runtime inputs without updating the lock and running the relevant tests. Native
binaries are generated under ignored build/dist folders and uploaded as release
assets, not committed to git. The published desktop builds are unsigned.

## Windows

Use Windows 10/11 x64 with .NET SDK 8, Python 3.11+ and NSIS 3 available. In
PowerShell at the repository root:

```powershell
./build.ps1
```

The script verifies the embedded Python archive, Microsoft VC runtime and all
locked CPU wheels, compiles the net48 WinForms app, assembles its runtime and
builds `dist/RamPilot-Setup-2.1.0.exe`. It does not bundle model weights. Runtime
provenance is in `runtime-lock.json`. Packaging does not rewrite that lock.

```powershell
dotnet build tests/DesktopTests.csproj -c Release -o build/tests
./build/tests/DesktopTests.exe
./build/engine/python/python.exe tests/test_streaming.py
```

The source tests use tiny random Qwen2 and Llama checkpoints and compare against
standard Hugging Face float32 results. They need no model download.

## Intel Mac

Use Python 3.12+ to prepare/package (the app itself embeds Python 3.11.10):

```sh
python mac/prepare_mac.py
python mac/package_mac.py
```

`mac/runtime-lock.json` pins the Astral Intel standalone CPython archive and
NumPy/regex/certifi wheels. Preparation verifies downloads before extraction.
Packaging creates a clean .app, preserves symlinks and executable permissions,
adds the app icon and writes the Intel Ventura ZIP. Signing/notarization is not
part of this development build. The optional `--reuse-runtime` switch is intended
only for local UI iteration against an already verified app.

On an Intel Mac, test the packaged engine:

```sh
APP_RES="$PWD/dist/RamPilot.app/Contents/Resources"
export TCL_LIBRARY="$APP_RES/python/lib/tcl8.6"
export TK_LIBRARY="$APP_RES/python/lib/tk8.6"
"$APP_RES/python/bin/python3" tests/native_numpy_smoke.py "$APP_RES/app"
"$APP_RES/python/bin/python3" -c 'import tkinter; r=tkinter.Tk(); r.update(); r.destroy()'
```

## Python regression suite

For example, on Linux with Python 3.11/3.12:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install torch==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r tests/requirements.txt
python tests/prepare_fixture.py --tokenizers-only
xvfb-run -a python -m unittest discover -s tests -p 'test_*.py' -v
python tests/native_numpy_smoke.py
```

Tk tests need a display; install Xvfb/Tk on Linux or use a native desktop. The
fixture command downloads only pinned tokenizer/config files with the flag above.
Without the flag it also downloads and verifies the real 0.5B weights (~1 GB).
`tests/CoreTests.cs` exercises C# client/server integration against that real
fixture; its optional second argument is the Python executable. Its test-only
Mono transport avoids Linux host network-interface restrictions.

## GitHub builds and releases

The Desktop checks and builds workflow runs Python checks on Ubuntu, creates the
Windows installer on Windows 2022, and packages the Mac app on Intel macOS 15.
It exercises the packaged native CPU runtimes and checks Windows setup/startup.
Actions are pinned to commit SHAs, and normal jobs receive read-only contents
permissions. Release upload alone receives contents:write.

After a verified source commit, publish a GitHub prerelease whose tag exactly
matches `v` plus VERSION (currently `v2.1.0`). The release event triggers checks
and both native builds. Only successful builds are uploaded, with SHA256SUMS.txt.
Until the workflow finishes, a release can exist without installers. Minimum
Ventura compatibility and physical device behavior still need separate testing.
