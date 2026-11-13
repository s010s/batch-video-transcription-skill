import unittest,tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import aliyun_sample as a,aliyun_batch as b,toolkit as t,videolib as v
class Recovery(unittest.TestCase):
    def test_get_retries_but_post_never_retries(self):
        api=a.WorkspaceAPI(a.DEFAULT_ORIGIN,a.SessionCredential('sk-fixture-NOT-REAL'))
        with patch.object(api,'_request_json_once',side_effect=[a.NetworkFailure('GET','TimeoutError'),{'ok':True}]) as once,patch.object(a.time,'sleep'):
            self.assertEqual(api.request_json('/api/v1/tasks/a'),{'ok':True});self.assertEqual(once.call_count,2)
        with patch.object(api,'_request_json_once',side_effect=a.NetworkFailure('POST','TimeoutError')) as once:
            with self.assertRaises(a.NetworkFailure):api.request_json('/api/v1/services/audio/asr/transcription','POST',{})
            self.assertEqual(once.call_count,1)
    def test_unknown_isolated_other_pending_submits_once_and_budget_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();work=Path(tmp)/'work';t.init(root,work);t.configure(work);s=b.Store(work/'task-state/tasks.json');jobs={}
            for name in ('a','b'):
                src=root/(name+'.mp4');src.write_bytes(b'source');audio=work/(name+'.wav');audio.write_bytes(b'audio');jobs[name]={'id':name,'relative_path':src.name,'source':v.source_stamp(src,False),'audio_path':str(audio),'audio_sha256':v.digest(audio),'duration_seconds':1,'status':'pending'}
            s.data.update(jobs=jobs,budget_microyuan=1000,approved_spending_cap_microyuan=1000,price_microyuan_per_second=10);s.save();api=Mock();api.submit.side_effect=[a.NetworkFailure('POST','URLError'),{'output':{'task_id':'known-id'}}]
            b.submit_one(s,api,'a',upload=lambda *args:'oss://synthetic');self.assertFalse(s.stop.is_set());b.submit_one(s,api,'b',upload=lambda *args:'oss://synthetic');self.assertEqual(api.submit.call_count,2);self.assertEqual(s.data['jobs']['a']['status'],'submission_uncertain');self.assertEqual(s.data['jobs']['b']['task_id'],'known-id');self.assertEqual(s.data['reserved_microyuan'],20)
            s.data.update(paused=True,reason='network_disk_or_submission_uncertain');s.save();b.resume_independent_pending(s);self.assertEqual(s.data['reserved_microyuan'],20);self.assertEqual(s.data['jobs']['a']['status'],'submission_uncertain')
            b.submit_all(s,api,upload=lambda *args:'oss://synthetic');self.assertEqual(api.submit.call_count,2)
    def test_get_failure_does_not_block_other_known_or_touch_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();work=Path(tmp)/'work';t.init(root,work);t.configure(work);s=b.Store(work/'task-state/tasks.json');s.data['jobs']={'a':{'id':'a','status':'submitted','task_id':'a-id'},'b':{'id':'b','status':'submitted','task_id':'b-id'},'c':{'id':'c','status':'submission_uncertain','reserved_microyuan':10}};s.data.update(reserved_microyuan=10,paused=True,reason='collect_interrupted_keep_task_ids');s.save();api=Mock();api.task.side_effect=[a.NetworkFailure('GET','TimeoutError'),{'output':{'task_status':'RUNNING'}}];b.collect(s,api,wait=False);self.assertEqual(api.task.call_count,2);api.submit.assert_not_called();self.assertEqual(s.data['jobs']['c']['status'],'submission_uncertain');self.assertEqual(s.data['reserved_microyuan'],10)

    def test_exhausted_upload_counts_as_incomplete_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();work=Path(tmp)/'work';t.init(root,work);t.configure(work);store=b.Store(work/'task-state/tasks.json');store.data['jobs']={'a':{'id':'a','status':'upload_failed'}}
            self.assertEqual(store.summary()['failed'],1)
            page=(Path(b.__file__).parent/'ui-v2.html').read_text();self.assertIn("upload_failed:'上传失败，尚未提交'",page)
