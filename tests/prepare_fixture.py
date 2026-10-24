import pathlib,json,urllib.request,hashlib,sys
root=pathlib.Path(__file__).resolve().parents[1];model=json.loads((root/'catalog.json').read_text())[0];folder=root/'tests/real-model';folder.mkdir(exist_ok=True)
for file in model['Files']:
 if '--tokenizers-only' in sys.argv and file['Name'].endswith('.safetensors'):continue
 p=folder/file['Name']
 if not p.exists():urllib.request.urlretrieve(file['Url'],p)
 with p.open('rb') as f:
  sha=hashlib.sha256()
  for block in iter(lambda:f.read(1048576),b''):sha.update(block)
 if sha.hexdigest()!=file['Sha256']:raise ValueError('Fixture checksum failed: '+p.name)
if '--tokenizers-only' not in sys.argv:(folder/'real.stream.json').write_text(json.dumps({'format':'rampilot-safetensors-v1','model_dir':str(folder)}))
print('Verified tokenizer fixture' if '--tokenizers-only' in sys.argv else 'Verified real-model fixture (about 1 GB on disk)')
