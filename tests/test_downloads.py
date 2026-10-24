import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mobile'))
import mobile_service as service

PAYLOAD=b'verified model fixture'
class Response(io.BytesIO):
    def __init__(self,payload,status=200,headers=None):
        super().__init__(payload);self.status=status;self.headers=headers or {'Content-Length':str(len(payload))}
    def geturl(self):return 'https://example.invalid/model.bin'

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        catalog=[dict(Name='Test',Bytes=len(PAYLOAD),FileName='model.stream.json',DirectoryName='model',Files=[dict(Name='model.bin',Bytes=len(PAYLOAD),Sha256=hashlib.sha256(PAYLOAD).hexdigest(),Url='https://example.invalid/model.bin')])]
        self.catalog=self.root/'catalog.json';self.catalog.write_text(json.dumps(catalog))
        service.configure(self.root,self.catalog);self.folder=self.root/'Models/model';self.folder.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def test_resumes_only_exact_range_then_verifies(self):
        (self.folder/'model.bin.part').write_bytes(PAYLOAD[:5])
        def open_request(request,**kwargs):
            self.assertEqual(request.get_header('Range'),'bytes=5-')
            return Response(PAYLOAD[5:],206,{'Content-Range':f'bytes 5-{len(PAYLOAD)-1}/{len(PAYLOAD)}','Content-Length':str(len(PAYLOAD)-5)})
        with patch.object(service.urllib.request,'urlopen',open_request):service.download(0)
        self.assertEqual((self.folder/'model.bin').read_bytes(),PAYLOAD)
        self.assertTrue(service.model_status()[0]['ready'])
    def test_bad_resume_never_becomes_ready(self):
        (self.folder/'model.bin.part').write_bytes(PAYLOAD[:5])
        response=Response(PAYLOAD[5:],206,{'Content-Range':'bytes 0-3/4'})
        with patch.object(service.urllib.request,'urlopen',return_value=response),self.assertRaises(OSError):service.download(0)
        self.assertFalse(service.model_status()[0]['ready'])
        self.assertEqual((self.folder/'model.bin.part').read_bytes(),PAYLOAD[:5])
    def test_corrupt_existing_file_is_preserved_and_replaced(self):
        (self.folder/'model.bin').write_bytes(b'broken')
        (self.root/'Models/model.stream.json').write_text('{}')
        with patch.object(service.urllib.request,'urlopen',return_value=Response(PAYLOAD)):service.download(0)
        self.assertEqual((self.folder/'model.bin').read_bytes(),PAYLOAD)
        self.assertEqual(next(self.folder.glob('*.corrupt-*')).read_bytes(),b'broken')
    def test_checksum_failure_invalidates_ready_marker(self):
        (self.root/'Models/model.stream.json').write_text('{}')
        with patch.object(service.urllib.request,'urlopen',return_value=Response(b'x'*len(PAYLOAD))),self.assertRaises(OSError):service.download(0)
        self.assertFalse(service.model_status()[0]['ready'])
        self.assertFalse((self.folder/'model.bin.part').exists())
    def test_second_verification_does_not_download_again(self):
        (self.folder/'model.bin').write_bytes(PAYLOAD)
        with patch.object(service.urllib.request,'urlopen',side_effect=AssertionError('Unexpected network')):service.download(0)
        self.assertTrue(service.model_status()[0]['ready'])
    def test_stop_during_response_preserves_partial_download(self):
        class Interrupted(Response):
            def read(self,n=-1):service.cancel();return super().read(n)
        with patch.object(service.urllib.request,'urlopen',return_value=Interrupted(PAYLOAD)),self.assertRaises(service.Stopped):service.download(0)
        self.assertTrue((self.folder/'model.bin.part').exists());self.assertFalse(service.model_status()[0]['ready'])

if __name__=='__main__':unittest.main(verbosity=2)
