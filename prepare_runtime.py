"""Assemble a self-contained Windows CPU runtime from pinned wheels."""
import zipfile,pathlib,json,hashlib,shutil,email
root=pathlib.Path(__file__).resolve().parent
expected=json.loads((root/'runtime-lock.json').read_text())
allowed={item['wheel']:item for item in expected}
archive=root/'vendor/python-3.11.9-embed-amd64.zip'
with archive.open('rb') as stream:
 if hashlib.file_digest(stream,'sha256').hexdigest()!='009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b':raise ValueError('Unverified Python runtime')
out=root/'build';(out/'engine/python/Lib/site-packages').mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(root/'vendor/python-3.11.9-embed-amd64.zip') as z:z.extractall(out/'engine/python')
(out/'engine/python/python311._pth').write_text('python311.zip\n.\nLib/site-packages\n../backend\nimport site\n')
packages=out/'engine/python/Lib/site-packages'
previous={i["wheel"]:i for i in json.loads((root/"runtime-lock.json").read_text())} if (root/"runtime-lock.json").exists() else {}
lock=[]
for item in expected:
 wheel=root/'vendor/wheels'/item['wheel']
 with wheel.open('rb') as stream:
  if hashlib.file_digest(stream,'sha256').hexdigest()!=item['sha256']:raise ValueError('Unverified wheel: '+wheel.name)
 with zipfile.ZipFile(wheel) as z:
  for n in z.namelist():
   if n.endswith('/'):continue
   if n.startswith('torch/include/') or (n.startswith('torch/') and n.endswith('.lib')):continue
   parts=pathlib.PurePosixPath(n).parts
   if any(p=='..' for p in parts):raise ValueError('Invalid wheel path')
   if parts[0].endswith('.data'):
    if len(parts)<3 or parts[1] not in ('purelib','platlib'):continue
    target=packages.joinpath(*parts[2:])
   else:target=packages.joinpath(*parts)
   target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(n))
  meta=next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
  data=email.message_from_bytes(z.read(meta))
  record=dict(name=data['Name'],version=data['Version'],wheel=wheel.name,sha256=hashlib.file_digest(wheel.open('rb'),'sha256').hexdigest(),requires=data.get_all('Requires-Dist') or [])
  if wheel.name in previous and 'url' in previous[wheel.name]:record['url']=previous[wheel.name]['url']
  lock.append(record)
# Keep backend outside the Python runtime directory for readable source and imports.
shutil.copytree(root/'backend',out/'engine/backend',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
# The source lock is immutable; never regenerate it from a build directory.
for name in ['RamPilot.ico','catalog.json']:shutil.copy2(root/name,out/name)
shutil.copy2(root/'src/RamPilot.exe.config',out/'RamPilot.exe.config')
print('Runtime bytes',sum(p.stat().st_size for p in (out/'engine').rglob('*') if p.is_file()))
print('Packages',[(p['name'],p['version']) for p in lock])
