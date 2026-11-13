import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import unittest
from unittest.mock import patch
import aliyun_live as live
import aliyun_sample as a

class LiveTests(unittest.TestCase):
    def test_policy_upload_no_bearer(self):
        class API:
            def request_json(self,path):
                self.path=path
                return {'data':{'upload_host':'https://test.oss-cn-beijing.aliyuncs.com', 'upload_dir':'dashscope-instant/a',
                  'oss_access_key_id':'SIGNED_ID','signature':'SIGNED_SIGNATURE','policy':'SIGNED_POLICY',
                  'x_oss_object_acl':'private','x_oss_forbid_overwrite':'true'}}
        api=API()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'a.wav';path.write_bytes(b'AUDIO')
            with patch.object(live,'safe_open',return_value=b'') as opened:
                url=live.upload(api,path)
            request=opened.call_args.args[0]
            self.assertNotIn('Authorization',dict(request.header_items()))
            body=b''.join(request.data);self.assertIn(b'SIGNED_SIGNATURE',body);self.assertIn(b'AUDIO',body)
            self.assertTrue(url.startswith('oss://dashscope-instant/a/sample-'))
            self.assertEqual(api.path,'/api/v1/uploads?action=getPolicy&model=fun-asr')
    def test_host_and_export_words(self):
        for url in ['http://test.oss-cn-beijing.aliyuncs.com','https://evil.test','https://test.oss-cn-shanghai.aliyuncs.com','https://test.oss-cn-beijing.aliyuncs.com@evil.test']:
            with self.assertRaises(ValueError):live.oss_endpoint(url)
        sample={'sample_id':'s','source_relative_path':'a.mov','offset_seconds':120,'duration_seconds':1}
        raw={'transcripts':[{'sentences':[{'begin_time':0,'end_time':1000,'text':'测试','speaker_id':0,'words':[{'begin_time':0,'end_time':500,'text':'测'}]}]}]}
        with tempfile.TemporaryDirectory() as d:
            doc=live.export(raw,sample,Path(d))
            self.assertEqual(doc['segments'][0]['start'],120)
            self.assertEqual(doc['segments'][0]['words_ms'][0]['end_time'],500)
            self.assertEqual(len(list(Path(d).iterdir())),7)
if __name__=='__main__':unittest.main()
