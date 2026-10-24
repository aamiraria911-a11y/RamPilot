"""Local desktop service for the Ventura app. Model weights stay on disk."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')
import gc
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import ssl
import threading
import time
import urllib.request
import uuid
from desktop_state import Conversations, atomic_json, read_json, normalize_settings, valid_history
from numpy_streamer import NumpyStreamingModel, Stopped
try:
    import certifi
    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = ssl.create_default_context()

_root = None
_catalog = []
_model = None
_history = []
_settings = normalize_settings({})
_conversations = None
_cancel = threading.Event()
_lock = threading.Lock()


def configure(root, catalog):
    global _root, _catalog, _history, _settings, _conversations
    _root = Path(str(root))
    _root.mkdir(parents=True, exist_ok=True)
    (_root / 'Models').mkdir(exist_ok=True)
    _catalog = json.loads(Path(str(catalog)).read_text('utf-8'))
    _settings = normalize_settings(read_json(_root / 'preferences.json', {}))
    _conversations = Conversations(_root)
    _history = read_json(_root / 'chat.json', []) if _settings['save_history'] else []
    if not valid_history(_history): _history = []
    return json.dumps(dict(models=model_status(), history=_history, settings=_settings,
                           conversations=_conversations.list()))


def model_status():
    return [dict(name=m['Name'], bytes=m['Bytes'], license=m.get('License', ''),
                 ready=(_root / 'Models' / m['FileName']).exists()) for m in _catalog]


def _notify(listener, method, *args):
    callback = getattr(listener, method, None) if listener is not None else None
    if callback: callback(*map(str, args))


def _check():
    if _cancel.is_set(): raise Stopped('Stopped. Partial downloads are preserved.')


def cancel():
    _cancel.set()
    if _model is not None: _model.cancel.set()


def _save():
    if _settings['save_history']:
        if _history:
            _settings['active_session'] = _conversations.save(_settings['active_session'], _history)
        atomic_json(_root / 'chat.json', _history)
    atomic_json(_root / 'preferences.json', _settings)


def save_settings(values):
    global _settings
    if not _lock.acquire(False): raise RuntimeError('Stop the current operation first')
    try:
        # Session identity belongs to the store, not to the settings form.
        values = dict(_settings, **values)
        values['active_session'] = _settings['active_session']
        _settings = normalize_settings(values)
        if not _settings['save_history']:
            (_root / 'chat.json').unlink(missing_ok=True)
        _save()
        return dict(_settings)
    finally:
        _lock.release()


def conversations():
    return _conversations.list()


def open_chat(identifier):
    global _history
    if not _lock.acquire(False): raise RuntimeError('Stop the current operation first')
    try:
        value = _conversations.load(identifier)
        _save()
        _settings['active_session'] = identifier
        _history = value['messages']
        _save()
        return list(_history)
    finally:
        _lock.release()


def new_chat():
    global _history
    if not _lock.acquire(False): raise RuntimeError('Stop the current operation first')
    try:
        _save()
        _history = []
        _settings['active_session'] = ''
        _save()
    finally:
        _lock.release()


def _safe_component(name):
    if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\\' in name:
        raise ValueError('Invalid catalog filename or directory')
    return name


def _verified(path, expected, listener):
    if not path.exists() or path.stat().st_size != expected['Bytes']: return False
    _notify(listener, 'onStatus', 'Verifying ' + expected['Name'])
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            _check()
            block = stream.read(1048576)
            if not block: break
            digest.update(block)
    return digest.hexdigest().lower() == expected['Sha256'].lower()


def download(index, listener=None):
    if not _lock.acquire(False): raise RuntimeError('Another operation is running')
    try:
        _cancel.clear()
        model = _catalog[int(index)]
        folder = _root / 'Models' / _safe_component(model['DirectoryName'])
        folder.mkdir(exist_ok=True)
        manifest = _root / 'Models' / _safe_component(model['FileName'])
        # A marker only means ready after the entire current verification succeeds.
        manifest.unlink(missing_ok=True)
        complete = 0
        started = time.monotonic()
        transferred = 0
        for file in model['Files']:
            _check()
            name = _safe_component(file['Name'])
            if not file['Url'].startswith('https://'):
                raise ValueError('Model downloads require HTTPS')
            path = folder / name
            part = folder / (name + '.part')
            if path.exists() and not _verified(path, file, listener):
                quarantine = path.with_name(path.name + '.corrupt-' + uuid.uuid4().hex[:8])
                path.rename(quarantine)
                _notify(listener, 'onStatus', 'Kept damaged file as ' + quarantine.name + '; downloading replacement')
            if not path.exists():
                offset = part.stat().st_size if part.exists() else 0
                if offset > file['Bytes']:
                    part.unlink(); offset = 0
                if shutil.disk_usage(_root).free < file['Bytes'] - offset + 256 * 1048576:
                    raise OSError('Not enough free disk space. Damaged files are preserved as .corrupt-*; remove them if no longer needed.')
                if offset < file['Bytes']:
                    headers = {'User-Agent': 'RamPilot/2.1'}
                    if offset: headers['Range'] = 'bytes=' + str(offset) + '-'
                    request = urllib.request.Request(file['Url'], headers=headers)
                    with urllib.request.urlopen(request, timeout=30, context=TLS) as response:
                        if not response.geturl().startswith('https://'):
                            raise OSError('The download redirected to an insecure connection')
                        if response.status == 206:
                            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                            if not match or tuple(map(int, match.groups())) != (offset, file['Bytes'] - 1, file['Bytes']):
                                raise OSError('The server returned an invalid resume range')
                        elif response.status == 200:
                            offset = 0
                        else:
                            raise OSError('Unexpected download response: ' + str(response.status))
                        length = response.headers.get('Content-Length')
                        if length is not None and int(length) != file['Bytes'] - offset:
                            raise OSError('Unexpected download size')
                        with part.open('ab' if offset else 'wb') as target:
                            last = 0
                            while True:
                                _check()
                                block = response.read(131072)
                                if not block: break
                                target.write(block)
                                offset += len(block); transferred += len(block)
                                if offset > file['Bytes']: raise OSError('Download exceeded expected size')
                                if time.monotonic() - last > .2:
                                    _notify(listener, 'onProgress', json.dumps(dict(done=complete+offset, total=model['Bytes'],
                                            bytes_per_second=transferred/max(.001,time.monotonic()-started))))
                                    last = time.monotonic()
                        if offset != file['Bytes']: raise OSError('Download interrupted. Download / resume will continue it.')
                if not _verified(part, file, listener):
                    part.unlink(missing_ok=True)
                    raise OSError('Checksum failed for ' + name + '. Download / resume to try again.')
                part.replace(path)
            complete += file['Bytes']
        _check()
        atomic_json(manifest, dict(format='rampilot-safetensors-v1', model_dir=model['DirectoryName'],
                                  repo=model.get('Repo'), revision=model.get('Revision')))
        _notify(listener, 'onProgress', json.dumps(dict(done=complete,total=model['Bytes'],bytes_per_second=0)))
        _notify(listener, 'onStatus', 'All files verified. Load the model to chat.')
        return 'Downloaded and verified'
    finally:
        _lock.release()


def load(index, context=512, budget_mib=2048, listener=None):
    model = _catalog[int(index)]
    if not (_root / 'Models' / model['FileName']).exists():
        raise ValueError('Download and verify this model first')
    return load_folder(str(_root / 'Models' / model['DirectoryName']), context, budget_mib, listener)


def load_folder(folder, context=512, budget_mib=2048, listener=None):
    global _model
    if not _lock.acquire(False): raise RuntimeError('Another operation is running')
    try:
        _cancel.clear(); _model = None; gc.collect()
        _notify(listener, 'onStatus', 'Reading metadata and tokenizer. Decoder weights stay on disk...')
        candidate = NumpyStreamingModel(str(folder), int(context), int(budget_mib))
        _check()
        _model = candidate
        _notify(listener, 'onStatus', 'Ready · ' + str(_model.layers) + ' layers · one block at a time')
        return 'Loaded'
    finally:
        _lock.release()


def unload():
    global _model
    if not _lock.acquire(False): raise RuntimeError('Stop the current operation first')
    try:
        _model = None; gc.collect()
    finally:
        _lock.release()


def is_loaded():
    return _model is not None

def current_history():
    return [dict(message) for message in _history]

def diagnostics():
    # No usernames, model paths, authentication tokens or chat text.
    return dict(app='RamPilot', version='2.1.0', platform=platform.system(),
                platform_release=platform.release(), machine=platform.machine(),
                python=platform.python_version(), cpu_count=os.cpu_count(),
                settings={k:_settings[k] for k in ['context','budget_mib','max_tokens','temperature','save_history']},
                engine=_model.metrics() if _model is not None else None)


def respond(text, max_tokens=None, listener=None):
    global _history
    if not _lock.acquire(False): raise RuntimeError('Another operation is running')
    try:
        if _model is None: raise ValueError('Download and load a model first')
        _cancel.clear()
        messages = [{'role':'system','content':_settings['system_prompt']}] + list(_history) + [{'role':'user','content':str(text)}]
        reply = max(1, min(int(max_tokens or _settings['max_tokens']), _model.context // 2))
        removed = 0
        while len(_model.tokenizer.encode(_model.tokenizer.chat(messages))) + reply > _model.context:
            if len(messages) <= 2: raise ValueError('Your message is too long for this context. Shorten it or increase Context and reload.')
            del messages[1:3]; removed += 1
        if removed: _notify(listener, 'onStatus', str(removed) + ' earlier turn(s) omitted from this request to fit context')
        last = [0.0]
        def progress(stats):
            _check()
            if time.monotonic() - last[0] > .2:
                _notify(listener, 'onMetrics', json.dumps(stats))
                last[0] = time.monotonic()
        _model.progress = progress
        answer = []
        for piece in _model.generate(messages, reply, _settings['temperature']):
            _check(); answer.append(piece); _notify(listener, 'onToken', piece)
        _check()
        complete = ''.join(answer)
        _history.extend([dict(role='user',content=str(text)), dict(role='assistant',content=complete)])
        _history = _history[-200:]
        _save()
        _notify(listener, 'onMetrics', json.dumps(_model.metrics()))
        _notify(listener, 'onStatus', 'Finished · weights and KV cache released')
        return complete
    finally:
        if _model is not None:
            _model.reset(); _model.progress = lambda s: None
        _lock.release()
