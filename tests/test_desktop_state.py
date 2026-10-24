import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mobile'))
from desktop_state import Conversations, atomic_json, normalize_settings, read_json

class DesktopStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Conversations(self.root)
        self.messages=[dict(role='user',content='سلام hello'),dict(role='assistant',content='Hi')]
    def tearDown(self):self.tmp.cleanup()
    def test_sessions_keep_identity_and_unicode(self):
        identifier=self.store.save('',self.messages)
        self.assertEqual(self.store.load(identifier)['messages'],self.messages)
        self.messages.extend([dict(role='user',content='Again'),dict(role='assistant',content='Yes')])
        self.assertEqual(self.store.save(identifier,self.messages),identifier)
        self.assertEqual(len(self.store.list()),1)
        self.assertEqual(self.store.list()[0]['turns'],2)
    def test_traversal_ids_are_rejected(self):
        for identifier in ['../chat','/tmp/chat','',None,'a'*33]:
            with self.subTest(identifier=identifier),self.assertRaises(ValueError):self.store.load(identifier)
    def test_partial_turn_is_never_saved(self):
        with self.assertRaises(ValueError):self.store.save('',self.messages[:1])
        self.assertEqual(self.store.list(),[])
    def test_corrupt_session_is_skipped(self):
        (self.store.folder/('a'*32+'.json')).write_text('null')
        (self.store.folder/'invalid.json').write_text('{}')
        self.assertEqual(self.store.list(),[])
    def test_bad_preferences_cannot_escape_supported_ranges(self):
        options=normalize_settings(dict(context='bad',budget_mib=-5,max_tokens=1e20,temperature=float('nan'),active_session='../bad'))
        self.assertEqual(options['context'],512);self.assertEqual(options['budget_mib'],512)
        self.assertEqual(options['max_tokens'],1024);self.assertEqual(options['temperature'],.7)
        self.assertEqual(options['active_session'],'')
    def test_atomic_write_and_read_recovery(self):
        path=self.root/'settings.json';atomic_json(path,dict(value='سلام'))
        self.assertEqual(read_json(path,{}),dict(value='سلام'))
        self.assertFalse(path.with_name('settings.json.tmp').exists())
        path.write_text('{');self.assertEqual(read_json(path,{}),{})

if __name__=='__main__':unittest.main(verbosity=2)
