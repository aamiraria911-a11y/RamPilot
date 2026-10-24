"""Regression tests for the Mac service's saved state and recovery paths."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mobile'))
import mobile_service as service
from numpy_streamer import Stopped

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = self.root / 'catalog.json'
        self.catalog.write_text(json.dumps([{'Name': 'Test', 'Bytes': 12,
            'FileName': 'test.stream.json', 'DirectoryName': 'test', 'Files': []}]))
        service._model = None
        service._cancel.clear()

    def tearDown(self):
        service.unload()
        self.temp.cleanup()

    def configure(self):
        return json.loads(service.configure(str(self.root), str(self.catalog)))

    def test_invalid_saved_history_does_not_block_startup(self):
        for content in ['{', '{}', 'null', '42', '"ab"', '[null,null]',
                        '["user","assistant"]', '[{},{}]',
                        '[{"role":"user","content":7},{"role":"assistant","content":"ok"}]']:
            with self.subTest(content=content):
                (self.root / 'chat.json').write_text(content)
                self.assertEqual(self.configure()['history'], [])

    def test_valid_history_is_preserved(self):
        history = [{'role': 'user', 'content': 'سلام'},
                   {'role': 'assistant', 'content': 'Hello'}]
        (self.root / 'chat.json').write_text(json.dumps(history))
        self.assertEqual(self.configure()['history'], history)
        service.new_chat()
        self.assertEqual(json.loads((self.root / 'chat.json').read_text()), [])

    def test_model_readiness_updates_without_reconfiguring_history(self):
        self.assertFalse(self.configure()['models'][0]['ready'])
        (self.root / 'Models/test.stream.json').write_text('{}')
        self.assertTrue(service.model_status()[0]['ready'])

    def test_interrupted_reply_releases_lock_and_preserves_history(self):
        self.configure()
        class Tokenizer:
            def chat(self, messages): return 'prompt'
            def encode(self, text): return [1]
        class Model:
            context = 512
            tokenizer = Tokenizer()
            cancel = threading.Event()
            resets = 0
            def generate(self, messages, reply, temperature=.7):
                yield 'partial'
                raise Stopped('Stopped')
            def reset(self): self.resets += 1
        model = Model()
        service._model = model
        with self.assertRaises(Stopped): service.respond('Hello')
        self.assertEqual(service._history, [])
        self.assertEqual(model.resets, 1)
        self.assertFalse(service._lock.locked())
        service.new_chat()

if __name__ == '__main__': unittest.main(verbosity=2)
