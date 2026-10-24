$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
function Fetch-Verified([string]$Url,[string]$Path,[string]$Hash) {
 if (!(Test-Path $Path) -or (Get-FileHash $Path -Algorithm SHA256).Hash -ne $Hash) {
  Invoke-WebRequest -UseBasicParsing $Url -OutFile "$Path.part"
  if ((Get-FileHash "$Path.part" -Algorithm SHA256).Hash -ne $Hash) {Remove-Item "$Path.part";throw "Checksum mismatch: $Path"}
  Move-Item -Force "$Path.part" $Path
 }
}
New-Item -ItemType Directory -Force 'vendor/wheels','build','dist' | Out-Null
Fetch-Verified 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' 'vendor/python-3.11.9-embed-amd64.zip' '009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b'
Fetch-Verified 'https://download.visualstudio.microsoft.com/download/pr/ebdab8e5-1d7b-4d9f-a11b-cbb1720c3b12/843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C/VC_redist.x64.exe' 'vendor/vc_redist.x64.exe' '843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c'
foreach($item in (Get-Content 'runtime-lock.json' -Raw | ConvertFrom-Json)) {Fetch-Verified $item.url (Join-Path 'vendor/wheels' $item.wheel) $item.sha256}
& dotnet build 'src/RamPilot.csproj' -c Release -o 'build'
if($LASTEXITCODE -ne 0){throw 'App compilation failed'}
& python 'prepare_runtime.py'
if($LASTEXITCODE -ne 0){throw 'Runtime packaging failed'}
Copy-Item 'catalog.json','RamPilot.ico' 'build/' -Force
Copy-Item 'src/RamPilot.exe.config' 'build/' -Force
$nsis=Get-Command makensis.exe -ErrorAction SilentlyContinue
if($null -eq $nsis){$compiler=Join-Path ${env:ProgramFiles(x86)} 'NSIS/makensis.exe'}else{$compiler=$nsis.Source}
foreach($requiredInput in @('vendor/vc_redist.x64.exe','build/RamPilot.exe','build/engine/python/python.exe')) {
 $verifiedInput=Join-Path $PSScriptRoot $requiredInput
 if(!(Test-Path -LiteralPath $verifiedInput -PathType Leaf)){throw "Missing installer input: $verifiedInput"}
 Write-Host "Installer input verified: $requiredInput"
}
& $compiler "/DPROJECT_ROOT=$PSScriptRoot" (Join-Path $PSScriptRoot 'installer/RamPilot.nsi')
if($LASTEXITCODE -ne 0){throw 'Installer build failed'}
Write-Host 'Built dist/RamPilot-Setup-2.1.0.exe'
