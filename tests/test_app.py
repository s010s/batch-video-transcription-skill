import contextlib,http.client,io,json,threading,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import app,aliyun_sample as auth,toolkit as t,videolib as v,aliyun_batch as b

class UIContracts(unittest.TestCase):
    def test_total_budget_deducts_prior_without_resetting_history(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work';t.init(root,work);t.configure(work)
            store=b.Store(work/'task-state/tasks.json');store.data.update(jobs={'x':{'id':'x','status':'pending'}},approved_spending_cap_microyuan=1983703);store.save()
            state=app.AppState(root,work,1983703,16297)
            with patch.object(auth,'WorkspaceAPI'),patch.object(b,'submit_all') as submit,patch.object(b,'collect'),patch.object(t,'publish'):
                state._execute('run',{'root':str(root),'work':str(work),'authorized':True,'total_budget':'2','key':'sk-fixture-NOT-REAL'})
                submit.assert_called_once()
            self.assertEqual(v.load(store.path)['budget_microyuan'],1983703)
            self.assertEqual(state.snapshot()['budget_mode'],'total')
    def test_blank_start_keeps_scope_unselected_and_carries_cap(self):
        state=app.AppState(spending_cap=1983703,prior_charge=16297)
        snap=state.snapshot()
        self.assertEqual(snap['root'],'');self.assertEqual(snap['work'],'')
        self.assertNotIn('summary',snap)
        self.assertAlmostEqual(snap['session_cap_yuan']+snap['prior_charge_yuan'],2)
    def test_session_cap_survives_user_selected_prepare_and_rejects_excess(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work'
            state=app.AppState(spending_cap=1983703,prior_charge=16297)
            with patch.object(t,'main'):
                state._execute('prepare',{'root':str(root),'work':str(work)})
            data=v.load(work/'task-state/tasks.json')
            self.assertEqual(data['approved_spending_cap_microyuan'],1983703)
            self.assertEqual(data['prior_potential_charge_microyuan'],16297)
            with patch.object(auth,'WorkspaceAPI') as api:
                state._execute('run',{'root':str(root),'work':str(work),'authorized':True,'budget':'2','key':'sk-fixture-NOT-REAL'})
                api.assert_not_called()
            self.assertIn('上限',state.message)
            self.assertIn('上限',state.snapshot()['error'])
    def test_refresh_preserves_only_local_session_fragment(self):
        page=app.PAGE.read_text()
        self.assertNotIn('history.replaceState',page)
        self.assertIn('location.hash.slice(1)',page)
        self.assertNotIn('body.key=',page.split('location.hash.slice(1)')[0])
    def test_explicit_budget_increase_can_resume_budget_stop(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work';t.init(root,work);t.configure(work)
            store=b.Store(work/'task-state/tasks.json');store.data.update(paused=True,reason='budget_limit',budget_microyuan=10000,price_microyuan_per_second=220,jobs={'x':{'id':'x','status':'pending'}});store.save()
            state=app.AppState(root,work)
            payload={'root':str(root),'work':str(work),'authorized':True,'budget':'.02','key':'sk-fixture-NOT-REAL'}
            with patch.object(auth,'WorkspaceAPI'),patch.object(b,'submit_all') as submit,patch.object(b,'collect'),patch.object(t,'publish'):
                state._execute('run',payload);submit.assert_called_once()
            final=v.load(store.path);self.assertEqual(final['budget_microyuan'],20000);self.assertIsNone(final['reason'])
    def test_safe_resume_known_id_but_not_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work';t.init(root,work);t.configure(work)
            store=b.Store(work/'task-state/tasks.json');store.data.update(paused=True,reason='user_pause',jobs={'x':{'id':'x','status':'submission_uncertain'}});store.save();(work/'pause.request').touch();s=app.AppState(root,work)
            s.resume()
            self.assertFalse((work/'pause.request').exists())
            self.assertEqual(v.load(store.path)['jobs']['x']['status'],'submission_uncertain')
            store.data['jobs']['x'].update(status='submitted',task_id='saved-task');store.save();s.resume()
            self.assertFalse((work/'pause.request').exists());self.assertEqual(v.load(store.path)['jobs']['x']['task_id'],'saved-task')
    def test_background_local_prepare_no_signal_error_or_network(self):
        import time
        from make_demo import generate
        with tempfile.TemporaryDirectory() as d:
            root=generate(Path(d)/'root');work=Path(d)/'work';s=app.AppState()
            with patch.object(auth,'WorkspaceAPI') as api:
                s.launch('prepare',{'root':str(root),'work':str(work)})
                deadline=time.monotonic()+20
                while s.busy and time.monotonic()<deadline:time.sleep(.05)
                self.assertFalse(s.busy);api.assert_not_called()
            self.assertIn('准备完成',s.message);self.assertEqual(s.snapshot()['summary']['total_videos'],4)
    def test_default_and_host_validation(self):
        self.assertEqual(auth.api_origin(auth.DEFAULT_ORIGIN),'https://dashscope.aliyuncs.com')
        for value in ['https://dashscope.aliyuncs.com.evil.test','https://dashscope-intl.aliyuncs.com','https://dashscope.aliyuncs.com:444','https://key@dashscope.aliyuncs.com']:
            with self.assertRaises(ValueError):auth.api_origin(value)
    def test_windows_cross_volume_links(self):
        self.assertEqual(v.local_media_url(r'D:\素材\你好 1.mp4',r'C:\输出'), 'file:///D:/%E7%B4%A0%E6%9D%90/%E4%BD%A0%E5%A5%BD%201.mp4')
        self.assertEqual(v.local_media_url(r'D:\素材\a.mp4',r'D:\输出'),'../%E7%B4%A0%E6%9D%90/a.mp4')
    def test_local_server_auth_origin_and_no_key_echo(self):
        state=app.AppState();token='synthetic-session-token';server=ThreadingHTTPServer(('127.0.0.1',0),app.handler_for(state,token));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path,headers=None,body=None):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port);c.request(method,path,body=body,headers=headers or {});r=c.getresponse();res=r.status,r.read();c.close();return res
        try:
            self.assertEqual(request('GET','/api/status')[0],403)
            self.assertEqual(request('GET','/api/status',{'X-Local-Token':token})[0],200)
            headers={'X-Local-Token':token,'Content-Type':'application/json','Origin':'https://evil.test'}
            self.assertEqual(request('POST','/api/run',headers,'{}')[0],403)
            headers['Origin']='http://127.0.0.1:'+str(server.server_port)
            with patch.object(state,'launch') as launch:
                status,body=request('POST','/api/collect',headers,json.dumps({'key':'sk-fixture-NOT-REAL'}))
                self.assertEqual(status,202);self.assertNotIn(b'sk-fixture',body);self.assertEqual(launch.call_count,1)
        finally:server.shutdown();server.server_close()
    def test_ui_source_no_storage_and_masked_field(self):
        page=app.PAGE.read_text()
        for bad in ['localStorage','sessionStorage','indexedDB']:self.assertNotIn(bad,page)
        self.assertIn('type="password"',page);self.assertIn("el('key').value=''",page)
    def test_unauthorized_run_does_not_create_api_and_payload_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work';t.init(root,work);s=app.AppState(root,work)
            payload={'root':str(root),'work':str(work),'key':'sk-fixture-NOT-REAL','budget':'.10','authorized':False}
            with patch.object(auth,'WorkspaceAPI') as api:s._execute('run',payload);api.assert_not_called()
            self.assertEqual(payload,{});self.assertNotIn('sk-fixture',s.message);self.assertFalse((work/'operation.lock').exists())
    def test_busy_denies_duplicate_start(self):
        s=app.AppState();s.busy=True
        with self.assertRaises(ValueError):s.launch('run',{})
    def test_legacy_tasks_require_known_origin(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work';t.init(root,work);t.configure(work)
            store=b.Store(work/'task-state/tasks.json');store.data['jobs']={'x':{'id':'x','status':'submitted','task_id':'prior'}};store.save()
            state=app.AppState(root,work)
            with patch.object(auth,'WorkspaceAPI') as api:
                state._execute('collect',{'root':str(root),'work':str(work),'key':'sk-fixture-NOT-REAL'});api.assert_not_called()
            self.assertIn('旧批次',state.message)
    def test_selected_sample_cannot_expand_on_prepare(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work';t.init(root,work);(work/'selected-sources.json').write_text('{}')
            with patch.object(v.Library,'scan') as scan:
                with self.assertRaises(ValueError):t.main(['prepare','--work',str(work)])
                scan.assert_not_called()
    def test_mock_single_key_session(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();work=Path(d)/'work';t.init(root,work);t.configure(work)
            store=b.Store(work/'task-state/tasks.json');store.data['jobs']={'x':{'id':'x','status':'submitted','task_id':'prior'}};store.save()
            s=app.AppState(root,work);payload={'root':str(root),'work':str(work),'key':'sk-fixture-NOT-REAL','origin':'https://workspace.cn-beijing.maas.aliyuncs.com'}
            with patch.object(auth,'WorkspaceAPI') as api,patch.object(b,'collect') as collect,patch.object(t,'publish'):
                s._execute('collect',payload);api.assert_called_once();collect.assert_called_once()
                credential=api.call_args.args[1]
                with self.assertRaises(ValueError):credential.header()
            self.assertEqual(payload,{})

if __name__=='__main__':unittest.main()

class ApprovedCeilingTests(unittest.TestCase):
    def test_ui_cannot_raise_explicit_batch_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();work=Path(tmp)/'work';t.init(root,work);t.configure(work)
            store=b.Store(work/'task-state/tasks.json');store.data['approved_spending_cap_microyuan']=100000;store.save()
            state=app.AppState(root,work)
            with patch.object(auth,'WorkspaceAPI') as api:
                state._execute('run',{'root':str(root),'work':str(work),'budget':'1','authorized':True,'key':'fixture-only'})
                api.assert_not_called()
            self.assertIn('批准总上限',state.message)
