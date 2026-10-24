"""Small, atomic local settings and conversation store. No inference dependency."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import uuid

DEFAULTS = dict(context=512, budget_mib=2048, max_tokens=128, temperature=0.7,
                system_prompt='You are a helpful assistant. Give clear, accurate answers.',
                save_history=True, active_session='', selected_model=0)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, fallback):
    try:
        if Path(path).stat().st_size > 16 * 1024 * 1024:
            return fallback
        return json.loads(Path(path).read_text('utf-8'))
    except (OSError, ValueError):
        return fallback


def valid_history(value):
    return (isinstance(value, list) and len(value) <= 200 and len(value) % 2 == 0
            and all(isinstance(m, dict) and m.get('role') == ('user' if i % 2 == 0 else 'assistant')
                    and isinstance(m.get('content'), str) and len(m['content']) <= 1_000_000
                    for i, m in enumerate(value)))


def normalize_settings(values):
    values = values if isinstance(values, dict) else {}
    result = DEFAULTS.copy()
    for key, minimum, maximum in [('context',64,2048), ('budget_mib',512,16384),
                                  ('max_tokens',1,1024), ('selected_model',0,1000)]:
        try:
            result[key] = max(minimum, min(maximum, int(values.get(key, result[key]))))
        except (ValueError, TypeError, OverflowError):
            pass
    try:
        temperature = float(values.get('temperature', result['temperature']))
        if math.isfinite(temperature):
            result['temperature'] = max(0, min(2, temperature))
    except (ValueError, TypeError, OverflowError):
        pass
    if isinstance(values.get('system_prompt'), str):
        result['system_prompt'] = values['system_prompt'][:10000]
    if isinstance(values.get('save_history'), bool):
        result['save_history'] = values['save_history']
    active = values.get('active_session')
    if isinstance(active, str) and re.fullmatch('[0-9a-f]{32}', active):
        result['active_session'] = active
    return result


class Conversations:
    def __init__(self, root):
        self.folder = Path(root) / 'Conversations'
        self.folder.mkdir(parents=True, exist_ok=True)

    def path(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{32}', identifier):
            raise ValueError('Invalid conversation identifier')
        return self.folder / (identifier + '.json')

    def save(self, identifier, messages, title=None):
        if not valid_history(messages) or not messages:
            raise ValueError('Only complete conversations can be saved')
        identifier = identifier or uuid.uuid4().hex
        path = self.path(identifier)
        old = read_json(path, {})
        if not isinstance(old, dict): old = {}
        now = datetime.now(timezone.utc).isoformat()
        previous_title = old.get('title') if isinstance(old.get('title'), str) else ''
        value = dict(id=identifier, title=(title or previous_title or messages[0]['content'].strip().split('\n')[0] or 'Untitled chat')[:80],
                     created=old.get('created', now), updated=now, messages=messages[-200:])
        atomic_json(path, value)
        return identifier

    def load(self, identifier):
        value = read_json(self.path(identifier), None)
        if not isinstance(value, dict) or value.get('id') != identifier or not valid_history(value.get('messages')):
            raise ValueError('This saved conversation is damaged or unavailable')
        return value

    def list(self):
        result = []
        for path in self.folder.glob('*.json'):
            try:
                item = self.load(path.stem)
                result.append(dict(id=item['id'], title=str(item.get('title', 'Untitled chat'))[:80],
                                   updated=str(item.get('updated', '')), turns=len(item['messages']) // 2))
            except (ValueError, OSError):
                continue
        return sorted(result, key=lambda item: item['updated'], reverse=True)
