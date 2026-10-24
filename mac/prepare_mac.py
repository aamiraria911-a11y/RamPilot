"""Download exact Intel Mac runtime inputs and check their publisher hashes."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def fetch(item, destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists() and hashlib.file_digest(destination.open('rb'),'sha256').hexdigest() == item['sha256']:
        return
    temporary = destination.with_name(destination.name+'.part')
    try:
        with urllib.request.urlopen(item['url'],timeout=60) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source,output,1024*1024)
        with temporary.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest() != item['sha256']:
                raise ValueError('Checksum mismatch: '+destination.name)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    lock = json.loads((ROOT/'mac/runtime-lock.json').read_text())
    archive = ROOT/'mac/vendor'/lock['python']['file']
    fetch(lock['python'],archive)
    target = ROOT/'mac/python'
    if target.exists(): shutil.rmtree(target)
    target.mkdir()
    with tarfile.open(archive,'r:gz') as source:
        source.extractall(target,filter='data')
    for item in lock['wheels']:
        fetch(item,ROOT/'mac/vendor/wheels'/item['file'])
    print('Verified Intel Python runtime and',len(lock['wheels']),'wheels')


if __name__ == '__main__': main()
