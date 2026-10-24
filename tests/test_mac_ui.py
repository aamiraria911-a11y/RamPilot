"""Tk regression tests; run with a display or Xvfb."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
BASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BASE / 'mobile'), str(BASE / 'mac')]
import mac_ui

@unittest.skipIf(sys.platform.startswith('linux') and not os.environ.get('DISPLAY'), 'Tk UI tests require a display or Xvfb')
class MacUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'HOME': self.temp.name})
        self.env.start()
        self.catalog = patch.object(mac_ui.service, 'configure', self.configure)
        self.original_configure = mac_ui.service.configure
        self.catalog.start()
        self.root = tk.Tk()
        self.app = mac_ui.App(self.root)
        self.root.update()
        self.loaded = patch.object(mac_ui.service, 'is_loaded', lambda: True)
        self.loaded.start()

    def configure(self, folder, catalog):
        return self.original_configure(folder, str(BASE / 'catalog.json'))

    def tearDown(self):
        self.loaded.stop()
        self.app.close()
        self.catalog.stop()
        self.env.stop()
        self.temp.cleanup()

    def settle(self):
        until = time.monotonic() + 4
        while self.app.busy and time.monotonic() < until:
            self.root.update()
            time.sleep(.01)
        self.root.update()
        self.assertFalse(self.app.busy)

    def test_controls_freeze_and_success_clears_prompt(self):
        entered = threading.Event()
        release = threading.Event()
        def respond(text, maximum, listener):
            entered.set()
            release.wait(2)
            listener.onToken('Hello')
        with patch.object(mac_ui.service, 'respond', respond):
            self.app.input.insert('1.0', 'Hi')
            self.app.send()
            self.assertTrue(entered.wait(1))
            self.assertEqual(str(self.app.models.cget('state')), 'disabled')
            self.assertEqual(str(self.app.context_entry.cget('state')), 'disabled')
            release.set()
            self.settle()
        self.assertEqual(self.app.input.get('1.0', 'end').strip(), '')
        self.assertIn('Hello', self.app.chat.get('1.0', 'end'))
        self.assertEqual(str(self.app.models.cget('state')), 'readonly')

    def test_stop_keeps_prompt_and_can_retry(self):
        def stopped(*args): raise mac_ui.Stopped('Stopped')
        with patch.object(mac_ui.service, 'respond', stopped):
            self.app.input.insert('1.0', 'Retry me')
            self.app.send()
            self.settle()
        self.assertEqual(self.app.status.get(), 'Stopped')
        self.assertEqual(self.app.input.get('1.0', 'end').strip(), 'Retry me')
        self.assertIn('Reply interrupted: Stopped', self.app.chat.get('1.0', 'end'))
        with patch.object(mac_ui.service, 'respond', lambda *args: None):
            self.app.send()
            self.settle()
        self.assertEqual(self.app.input.get('1.0', 'end').strip(), '')

    def test_load_captures_widget_values_on_main_thread(self):
        main_thread = threading.get_ident()
        original = self.app.parameters
        def parameters():
            self.assertEqual(threading.get_ident(), main_thread)
            return original()
        self.app.parameters = parameters
        values = []
        with patch.object(mac_ui.service, 'load', lambda *args: values.append(args[:3])):
            self.app.context.set('256')
            self.app.budget.set('1024')
            self.app.load()
            self.settle()
        self.assertEqual(values, [(0, 256, 1024)])
        self.assertTrue(self.app.input.winfo_viewable())
        self.assertGreater(self.app.input.winfo_height(), 20)

if __name__ == '__main__': unittest.main(verbosity=2)
