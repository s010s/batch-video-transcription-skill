import concurrent.futures,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import aliyun_batch as b,aliyun_sample as a,toolkit as t,videolib as v,workflow_state as wf,app

class ReleaseInvariants(unittest.TestCase):
    def make(self,tmp,n=1):
        root=Path(tmp)/'root';root.mkdir();work=Path(tmp)/'work';t.init(root,work);t.configure(work);s=b.Store(work/'task-state/tasks.json');jobs={}
        for i in range(n):
            name=str(i);source=root/(name+'.mp4');source.write_bytes(b'source');audio=work/(name+'.wav');audio.write_bytes(b'audio');jobs[name]={'id':name,'relative_path':source.name,'source':v.source_stamp(source,False),'status':'pending','audio_path':str(audio),'audio_sha256':v.digest(audio),'duration_seconds':1}
        s.data.update(jobs=jobs,budget_microyuan=1000,price_microyuan_per_second=10);s.save();return s
    def test_unknown_retry_opt_in_is_bounded_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);api=Mock();api.submit.side_effect=a.NetworkFailure('POST','TimeoutError')
            b.submit_one(s,api,'0',lambda *args:'oss://synthetic');self.assertEqual(api.submit.call_count,1)
            s.data['unknown_retry_policy']={'accept_duplicate_cost':True,'max_extra_attempts':1};s.save()
            with patch.object(b.time,'sleep'):b.submit_one(s,api,'0',lambda *args:'oss://synthetic')
            self.assertEqual(api.submit.call_count,2);self.assertEqual(s.data['reserved_microyuan'],20)
            restarted=b.Store(s.path);b.submit_one(restarted,api,'0',lambda *args:'oss://synthetic');self.assertEqual(api.submit.call_count,2)
            self.assertEqual(len(restarted.data['jobs']['0']['attempt_history']),2)
    def test_late_receipt_never_overwrites_new_attempt(self):
        data={'reserved_microyuan':0,'budget_microyuan':100,'unknown_retry_policy':{'accept_duplicate_cost':True,'max_extra_attempts':1}}
        job={'status':'pending'};one=wf.reserve_attempt(data,job,10);two=wf.reserve_attempt(data,job,10);wf.record_id(job,two,'new-id');wf.record_id(job,one,'late-old-id');self.assertEqual(job['task_id'],'new-id');self.assertEqual(job['attempt_history'][0]['task_id'],'late-old-id');self.assertEqual(data['reserved_microyuan'],20)
    def test_concurrent_retry_and_pending_never_exceed_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp,3);s.data.update(budget_microyuan=20,unknown_retry_policy={'accept_duplicate_cost':True,'max_extra_attempts':2});s.save();api=Mock();api.submit.side_effect=a.NetworkFailure('POST','TimeoutError')
            with patch.object(b.time,'sleep'):b.submit_all(s,api,lambda *args:'oss://synthetic')
            self.assertLessEqual(s.data['reserved_microyuan'],20);self.assertLessEqual(api.submit.call_count,2);self.assertEqual(sum(j.get('reserved_microyuan',0) for j in s.data['jobs'].values()),s.data['reserved_microyuan'])
    def test_receipt_failure_prevents_post_and_explicit_repair_keeps_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);api=Mock();real=v.atomic_json
            def fail_backup(path,data):
                if Path(path).name=='任务清单.json':raise OSError('synthetic disk fault')
                return real(path,data)
            with patch.object(v,'atomic_json',side_effect=fail_backup):b.submit_one(s,api,'0',lambda *args:'oss://synthetic')
            api.submit.assert_not_called();self.assertTrue(s.journal.exists());self.assertEqual(s.data['reserved_microyuan'],10)
            restarted=b.Store(s.path);self.assertTrue(restarted.recovery_required)
            before=s.path.read_bytes()
            with self.assertRaises(ValueError):b.prepare(s.path)
            self.assertEqual(s.path.read_bytes(),before)
            restarted.repair_receipts();self.assertFalse(restarted.journal.exists());self.assertEqual(restarted.data['reserved_microyuan'],10);self.assertEqual(restarted.data['reason'],'user_pause');self.assertEqual(v.load(restarted.path),v.load(restarted.output_root/'转写结果/任务清单.json'))
    def test_restart_reads_saved_prior_and_cap_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);s.data.update(prior_potential_charge_microyuan=123,approved_spending_cap_microyuan=500,budget_microyuan=400);s.save();state=app.AppState(s.root,s.path.parent.parent);snap=state.snapshot();self.assertEqual(snap['prior_charge_yuan'],.000123);self.assertEqual(snap['session_cap_yuan'],.0005)
            with self.assertRaises(ValueError):wf.budget_context(s.data,0,None)
    def test_failed_diagnostic_get_fault_does_not_block_later_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp,3)
            for i,j in s.data['jobs'].items():j.update(status='submitted',task_id='task-'+i)
            s.data['jobs']['0']['status']='failed';s.save();api=Mock();api.task.side_effect=[a.NetworkFailure('GET','TimeoutError'),{'output':{'task_status':'RUNNING'}},{'output':{'task_status':'RUNNING'}}]
            b.collect(s,api,export=False,wait=False);self.assertEqual(api.task.call_count,3);self.assertFalse(s.stop.is_set());self.assertTrue(s.data['jobs']['0']['collection_deferred'])
    def test_deferred_get_is_revisited_same_session_then_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);s.data['jobs']['0'].update(status='submitted',task_id='task');s.save();api=Mock();api.task.side_effect=a.NetworkFailure('GET','TimeoutError')
            with patch.object(b.time,'sleep'):b.collect(s,api,export=False,wait=True)
            self.assertEqual(api.task.call_count,3);self.assertEqual(s.data['jobs']['0']['status'],'submitted');self.assertTrue(s.data['jobs']['0']['collection_deferred']);api.submit.assert_not_called()

    def test_cli_authorization_uses_saved_history_and_explicit_retry_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);s.data.update(prior_potential_charge_microyuan=100,approved_spending_cap_microyuan=900);s.save()
            args=['authorize','--work',str(s.path.parent.parent),'--budget-yuan','0.001','--price-yuan-per-second','0.00001','--upload-authorized','--paid-authorized']
            t.main(args);saved=b.Store(s.path);self.assertEqual(saved.data['budget_microyuan'],900)
            with self.assertRaises(ValueError):t.main(args+['--max-unknown-retries','1'])
            t.main(args+['--max-unknown-retries','1','--accept-duplicate-cost']);saved=b.Store(s.path);self.assertTrue(saved.data['unknown_retry_policy']['accept_duplicate_cost'])
    def test_late_id_survives_other_response_backup_failure(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp,2);barrier=threading.Barrier(2);first_failed=threading.Event();api=Mock();real=v.atomic_json
            def post(*args,**kwargs):
                thread=threading.current_thread().name;barrier.wait(timeout=5)
                if thread=='second':first_failed.wait(timeout=5)
                return {'output':{'task_id':'id-'+thread}}
            def write(path,data):
                if Path(path).name=='任务清单.json' and any(j.get('task_id') for j in data.get('jobs',{}).values()):first_failed.set();raise OSError('synthetic backup fault')
                return real(path,data)
            api.submit.side_effect=post
            with patch.object(v,'atomic_json',side_effect=write):
                one=threading.Thread(name='first',target=b.submit_one,args=(s,api,'0',lambda *x:'oss://synthetic'));two=threading.Thread(name='second',target=b.submit_one,args=(s,api,'1',lambda *x:'oss://synthetic'));one.start();two.start();one.join(8);two.join(8);self.assertFalse(one.is_alive() or two.is_alive())
            restarted=b.Store(s.path);restarted.repair_receipts();self.assertEqual({j['task_id'] for j in restarted.data['jobs'].values()},{'id-first','id-second'});self.assertEqual(restarted.data['reserved_microyuan'],20);self.assertEqual(api.submit.call_count,2)
    def test_response_inbox_recovers_crash_before_aggregate_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);job=s.data['jobs']['0'];number=wf.reserve_attempt(s.data,job,10);s.save();s.persist_response('0',number,'late-id')
            restarted=b.Store(s.path);self.assertTrue(restarted.recovery_required);restarted.repair_receipts();self.assertEqual(restarted.data['jobs']['0']['task_id'],'late-id')
    def test_retry_upload_failure_preserves_original_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);api=Mock();api.submit.side_effect=a.NetworkFailure('POST','TimeoutError');b.submit_one(s,api,'0',lambda *x:'oss://synthetic');s.data['unknown_retry_policy']={'accept_duplicate_cost':True,'max_extra_attempts':1};s.save()
            upload=Mock(side_effect=a.NetworkFailure('POST','TimeoutError'))
            with patch.object(b.time,'sleep'):b.submit_one(s,api,'0',upload)
            self.assertEqual(s.summary()['uncertain'],1);self.assertEqual(s.data['reserved_microyuan'],10);self.assertEqual(api.submit.call_count,1);self.assertEqual(upload.call_count,3)
    def test_prepare_restart_does_not_zero_saved_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.make(tmp);s.data.update(prior_potential_charge_microyuan=123,approved_spending_cap_microyuan=900);s.save();state=app.AppState(s.root,s.path.parent.parent,spending_cap=900)
            with patch.object(t,'main'):state._execute('prepare',{'root':str(s.root),'work':str(s.path.parent.parent)})
            self.assertFalse(state.error);self.assertEqual(b.Store(s.path).data['prior_potential_charge_microyuan'],123)
