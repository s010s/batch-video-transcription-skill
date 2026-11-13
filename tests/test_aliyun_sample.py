import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import aliyun_sample as a


class AliyunContractsTests(unittest.TestCase):
    def test_origin_and_no_guessing(self):
        self.assertEqual(a.api_origin('https://workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'),'https://workspace123.cn-beijing.maas.aliyuncs.com')
        for url in ('https://evil.test/compatible-mode/v1','https://workspace.ap-southeast-1.maas.aliyuncs.com','http://workspace.cn-beijing.maas.aliyuncs.com','https://key@workspace.cn-beijing.maas.aliyuncs.com','https://workspace.cn-beijing.maas.aliyuncs.com/?key=secret','https://workspace.cn-beijing.maas.aliyuncs.com:sk-ws-secret'):
            with self.assertRaises(ValueError):a.api_origin(url)
    def test_hidden_input_refuses_non_tty(self):
        with patch.object(a.sys,'stdin',io.StringIO('fake')),patch.object(a.getpass,'getpass') as get:
            with self.assertRaises(ValueError):a.SessionCredential.prompt()
            get.assert_not_called()
        secret='sk-ws-TESTONLY123456';credential=a.SessionCredential(secret)
        self.assertNotIn(secret,repr(credential));credential.close()
        with self.assertRaises(ValueError):credential.header()
    def test_new_key_printable_characters_and_header_safety(self):
        # Synthetic values only: no minimum length or punctuation whitelist.
        for secret in ('sk', 'sk.x-y_z', 'sk-ws.a+b/c=:@!~', 'sk short printable'):
            credential=a.SessionCredential('  '+secret+'  ')
            self.assertEqual(credential.header(),'Bearer '+secret)
            self.assertNotIn(secret,repr(credential))
            credential.close()
        for secret in ('SK.x', 'prefix-sk', 'sk.a\nb', 'sk.a\rb', 'sk.a\tb',
                       'sk.a\x00b', 'sk.a\x1fb', 'sk.a\x7fb', 'sk.a\x85b', 'sk.a\u2028b'):
            with self.assertRaises(ValueError) as error:a.SessionCredential(secret)
            self.assertNotIn(secret,str(error.exception))
        with patch.object(a.sys.stdin,'isatty',return_value=True),patch.object(a.getpass,'getpass',return_value='  sk.new-format_1  '):
            credential=a.SessionCredential.prompt()
            self.assertEqual(credential.header(),'Bearer sk.new-format_1')
            credential.close()
    def test_bearer_destination_and_upload_closed(self):
        credential=a.SessionCredential('sk-ws-TESTONLY123456')
        api=a.WorkspaceAPI('https://workspace.cn-beijing.maas.aliyuncs.com',credential)
        with self.assertRaises(ValueError):api.submit('oss://temporary/test.wav')
        with self.assertRaises(ValueError):api.request_json('https://evil.test')
        request=a.WorkspaceAPI.submit_contract('oss://temporary/test.wav')
        self.assertTrue(request['parameters']['diarization_enabled']);self.assertEqual(request['parameters']['channel_id'],[0])
    def test_same_speaker_pauses_and_a_b_a(self):
        def segment(speaker,start,end,text,**extra):
            return {'speaker':speaker,'start':start,'end':end,'text':text,**extra}
        sentences=[segment('A',0,1,'一'),segment('A',3,4,'二'),segment('A',12,13,'三'),segment('B',14,15,'四'),segment('A',16,17,'五')]
        turns=a.merge_turns(sentences)
        self.assertEqual([t['speaker'] for t in turns],['A','B','A'])
        self.assertEqual(turns[0]['texts'],['一','二','三'])
        self.assertEqual((turns[0]['start'],turns[0]['end']),(0,13))
        boundary=[sentences[0],{**sentences[1],'splice_boundary':True}]
        self.assertEqual(len(a.merge_turns(boundary)),2)
        unknown=[sentences[0],segment(None,2,3,'未知'),sentences[2]]
        self.assertEqual(len(a.merge_turns(unknown)),3)
    def test_offsets_scope_and_unknown_turns(self):
        sample={'sample_id':'clip1','source_relative_path':'采访.mp4','offset_seconds':120,'duration_seconds':10}
        raw={'transcripts':[{'sentences':[{'begin_time':0,'end_time':1000,'text':'A','speaker_id':0},{'begin_time':1000,'end_time':2000,'text':'B','speaker_id':0},{'begin_time':2000,'end_time':3000,'text':'C','speaker_id':1},{'begin_time':3000,'end_time':4000,'text':'D','speaker_id':0},{'begin_time':4000,'end_time':5000,'text':'U'},{'begin_time':5000,'end_time':6000,'text':'V'}]}]}
        doc=a.normalize_result(raw,sample);turns=a.merge_turns(doc['segments'])
        self.assertEqual(doc['segments'][0]['start'],120);self.assertEqual(turns[0]['end'],122)
        self.assertEqual(turns[0]['texts'],['A','B']);self.assertEqual(len(turns),5)
        other=a.normalize_result(raw,{**sample,'sample_id':'clip2'})
        self.assertNotEqual(doc['segments'][0]['speaker'],other['segments'][0]['speaker'])
        overlap=[{**doc['segments'][0]},{**doc['segments'][1],'start':120.5}]
        self.assertEqual(len(a.merge_turns(overlap)),2)
        gap=[doc['segments'][0],{**doc['segments'][1],'start':124,'end':125}]
        self.assertEqual(len(a.merge_turns(gap,max_gap_seconds=2)),2)


if __name__=='__main__':unittest.main()
