import contextlib,io,json,hashlib,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import toolkit as t
import aliyun_live as live
import aliyun_sample as auth
import aliyun_batch as batch
import videolib as v
from make_demo import generate

class ToolkitTests(unittest.TestCase):
    def call(self,args):
        with contextlib.redirect_stdout(io.StringIO()):t.main(args)
    def test_offline_end_to_end_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root=generate(base/'素材');work=base/'batch'
            originals={str(p.relative_to(root)):v.digest(p) for p in root.rglob('*') if p.is_file()}
            self.call(['init','--root',str(root),'--work',str(work)])
            with patch.object(auth.WorkspaceAPI,'request_json',side_effect=AssertionError('unexpected network')):
                self.call(['prepare','--work',str(work)])
                data=v.load(work/'task-state/tasks.json');self.assertEqual(len(data['jobs']),4);self.assertEqual(data['budget_microyuan'],0)
                self.assertEqual(sum(j['status']=='no_audio' for j in data['jobs'].values()),1)
                ready=[j for j in data['jobs'].values() if j['status']=='pending'];self.assertEqual(len(ready),2)
                audio_mtimes={j['audio_path']:Path(j['audio_path']).stat().st_mtime_ns for j in ready}
                self.call(['prepare','--work',str(work)])
                self.assertEqual(audio_mtimes,{p:Path(p).stat().st_mtime_ns for p in audio_mtimes})
                with self.assertRaises(ValueError):self.call(['submit','--work',str(work)])
                t.configure(work);store=batch.Store(work/'task-state/tasks.json');job=store.data['jobs'][ready[0]['id']]
                # Synthetic provider result, not a real recognition or paid call.
                raw={'transcripts':[{'sentences':[{'begin_time':200,'end_time':1400,'text':'合成测试 <script> 关键词','speaker_id':0}]}]}
                out=work/'task-state/results'/job['id'];out.mkdir(parents=True)
                v.atomic_json(out/'raw-response.json',raw)
                live.export(raw,{'sample_id':job['id'],'source_relative_path':job['relative_path'],'offset_seconds':0,'duration_seconds':job['duration_seconds']},out)
                job.update(status='downloaded',result_dir=str(out));store.save();batch.export_job(store,job);t.publish()
                self.assertTrue(list((Path(store.data['output_root'])/'转写结果明细').rglob('*.docx')))
                self.assertTrue((Path(store.data['output_root'])/'转写结果/视频文字稿.html').is_file())
                payload=(Path(store.data['output_root'])/'转写结果/data.js').read_text();self.assertNotIn('<script>',payload);self.assertIn('关键词',payload)
                self.assertEqual(originals,{name:v.digest(root/name) for name in originals})
                batch.export_job(store,job) # Exact same version is safely reusable.
                word=store.output_root/job['export_receipt']['word_relative_path'];word.write_bytes(word.read_bytes()+b'user-edit')
                with self.assertRaisesRegex(ValueError,'Word'):batch.export_job(store,job)
                self.assertTrue(word.read_bytes().endswith(b'user-edit'))
    def test_pause_during_inflight_submit_keeps_dual_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root=base/'root';root.mkdir();src=root/'a.mp4';src.write_bytes(b'source');work=base/'work'
            t.init(root,work);t.configure(work);store=batch.Store(work/'task-state/tasks.json')
            audio=work/'a.wav';audio.write_bytes(b'audio')
            job={'id':'a','relative_path':'a.mp4','source':v.source_stamp(src,False),'audio_path':str(audio),'audio_sha256':v.digest(audio),'duration_seconds':1,'status':'pending'}
            store.data.update(jobs={'a':job},budget_microyuan=1000,price_microyuan_per_second=10);store.save()
            class API:
                def submit(self,*args,**kwargs):
                    (work/'pause.request').touch()
                    return {'output':{'task_id':'saved-id'}}
            batch.submit_one(store,API(),'a',upload=lambda *args:'oss://test')
            self.assertEqual(v.load(store.path)['jobs']['a']['task_id'],'saved-id')
            backup=store.output_root/'转写结果/任务清单.json'
            self.assertEqual(v.load(backup)['jobs']['a']['task_id'],'saved-id')
            store.pause('user_pause');(work/'pause.request').unlink();batch.require_resume_allowed(store)
    def test_pause_does_not_overwrite_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d);r=b/'r';r.mkdir();w=b/'w';t.init(r,w)
            before=(w/'task-state/tasks.json').read_bytes()
            self.call(['pause','--work',str(w)])
            self.assertEqual(before,(w/'task-state/tasks.json').read_bytes())
            self.assertTrue((w/'pause.request').exists())
    def test_lock_prevents_manifest_access(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d);r=b/'r';r.mkdir();w=b/'w';t.init(r,w);(w/'operation.lock').write_text('{}')
            with patch.object(batch,'Store',side_effect=AssertionError('manifest read before lock')):
                with self.assertRaises(ValueError):self.call(['prepare','--work',str(w)])
    def test_collect_does_not_resubmit_after_failure(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d);r=b/'r';r.mkdir();w=b/'w';t.init(r,w);t.configure(w);store=batch.Store(w/'task-state/tasks.json')
            store.data['jobs']={'x':{'id':'x','status':'submitted','task_id':'previous-id','relative_path':'a.mp4','duration_seconds':1}}
            class API:
                def task(self,id):return {'output':{'task_status':'FAILED'}}
                def submit(self,*args,**kwargs):raise AssertionError('duplicate submit')
            batch.collect(store,API(),export=False)
            self.assertEqual(store.data['jobs']['x']['status'],'failed')
            self.assertEqual(store.data['jobs']['x']['task_id'],'previous-id')
    def test_concurrent_budget_never_overreserves(self):
        import concurrent.futures,threading
        with tempfile.TemporaryDirectory() as d:
            b=Path(d);r=b/'r';r.mkdir();w=b/'w';t.init(r,w);t.configure(w);store=batch.Store(w/'task-state/tasks.json')
            jobs={}
            for name in ['a','b']:
                src=r/(name+'.mp4');src.write_bytes(name.encode());au=w/(name+'.wav');au.write_bytes(b'audio')
                jobs[name]={'id':name,'relative_path':src.name,'source':v.source_stamp(src,False),'audio_path':str(au),'audio_sha256':v.digest(au),'duration_seconds':1,'status':'pending'}
            store.data.update(jobs=jobs,budget_microyuan=10,price_microyuan_per_second=10);store.save();barrier=threading.Barrier(2)
            def upload(*unused):barrier.wait(timeout=5);return 'oss://test'
            class API:
                calls=0
                def submit(self,*args,**kwargs):self.calls+=1;return {'output':{'task_id':'only-one'}}
            api=API()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda name:batch.submit_one(store,api,name,upload=upload),jobs))
            self.assertEqual(api.calls,1);self.assertEqual(store.data['reserved_microyuan'],10)
            self.assertEqual(store.data['reason'],'budget_limit')
    def test_pause_never_overwrites_existing_failure(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d);r=b/'r';r.mkdir();w=b/'w';t.init(r,w);t.configure(w);store=batch.Store(w/'task-state/tasks.json')
            store.pause('network_disk_or_submission_uncertain');(w/'pause.request').touch()
            store.pause('user_pause') # Same shared method used by the signal handler.
            batch.submit_all(store,object())
            self.assertEqual(v.load(store.path)['reason'],'network_disk_or_submission_uncertain')
            with self.assertRaises(ValueError):batch.require_resume_allowed(store)
    def test_transport_secrets_not_saved_but_text_unchanged(self):
        raw={'file_url':'https://oss.test/a?signature=PRIVATE','authorization':'Bearer PRIVATE','transcripts':[{'sentences':[{'text':'原文 signature=spoken','begin_time':0,'end_time':1}]}]}
        cleaned=live.safe_result(raw)
        self.assertNotIn('PRIVATE',json.dumps(cleaned));self.assertEqual(cleaned['transcripts'][0]['sentences'][0]['text'],'原文 signature=spoken')
    def test_budget_and_nonfinite(self):
        for n in ['nan','Infinity','0','-1']:
            with self.assertRaises(ValueError):t.amount(n)
        self.assertEqual(t.amount('0.00022'),220)
    def test_auth_override_and_public_acl(self):
        credential=auth.SessionCredential('sk-test-fixture-not-a-real-secret')
        api=auth.WorkspaceAPI('https://example.cn-beijing.maas.aliyuncs.com',credential)
        with self.assertRaises(ValueError):api.request_json('/api/v1/models',extra_headers={'authorization':'bad'})
        class Fake:
            def request_json(self,p):return {'data':{'x_oss_object_acl':'public-read'}}
        with self.assertRaises(ValueError):live.upload(Fake(),Path('unused'))
        credential.close()
    def test_uncertain_not_resubmitted(self):
        class Store:
            import threading
            stop=threading.Event()
            data={'jobs':{'x':{'id':'x','status':'submission_uncertain'}}}
            def summary(self):return {}
        with patch.object(batch,'submit_one') as submit:
            batch.submit_all(Store(),object());submit.assert_not_called()

if __name__=='__main__':unittest.main()

class CollectionRecoveryTests(unittest.TestCase):
    def test_query_retry_keeps_ids_and_drops_exception_secrets(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work'
            t.init(root,work);t.configure(work);store=batch.Store(work/'task-state/tasks.json')
            store.data['jobs']={'a':{'id':'a','status':'submitted','task_id':'task-123'}};store.save()
            api=SimpleNamespace(task=lambda _: (_ for _ in ()).throw(ValueError('secret-value https://signed.invalid/?token=secret')))
            batch.collect(store,api,export=False)
            self.assertIsNone(store.data['reason']);self.assertTrue(store.data['jobs']['a']['collection_deferred'])
            self.assertNotIn('secret',json.dumps(store.data))
            self.assertEqual(store.data['jobs']['a']['collection_diagnostic']['stage'],'task_query')
            api=SimpleNamespace(task=lambda _: {'output':{'task_status':'RUNNING'}})
            store=batch.Store(work/'task-state/tasks.json')
            batch.collect(store,api,export=False)
            self.assertFalse(store.data['paused']);self.assertEqual(store.data['jobs']['a']['task_id'],'task-123')
