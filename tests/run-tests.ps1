$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
if(!(Test-Path 'build/engine/python/python.exe')){throw 'Run build.ps1 first'}
& python 'tests/prepare_fixture.py'
if($LASTEXITCODE -ne 0){throw 'Fixture preparation failed'}
& dotnet build 'tests/CoreTests.csproj' -c Release -o 'tests/bin'
if($LASTEXITCODE -ne 0){throw 'Test compilation failed'}
& './tests/bin/CoreTests.exe' $projectRoot
if($LASTEXITCODE -ne 0){throw 'Integration tests failed'}
