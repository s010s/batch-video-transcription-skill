import json,subprocess,unittest
from pathlib import Path
import app

class StateGuidedUITests(unittest.TestCase):
    def test_default_http_entry_serves_state_guided_ui(self):
        import http.client,threading
        from http.server import ThreadingHTTPServer
        self.assertEqual(app.PAGE.name,'ui-v2.html')
        server=ThreadingHTTPServer(('127.0.0.1',0),app.handler_for(app.AppState(),'synthetic-token'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=http.client.HTTPConnection('127.0.0.1',server.server_port)
            client.request('GET','/');response=client.getresponse();body=response.read().decode();client.close()
            self.assertEqual(response.status,200)
            self.assertIn('TRANSCRIPTION WORKSPACE',body)
            self.assertIn('继续收取结果',body)
            self.assertIn('id="primary"',body)
        finally:server.shutdown();server.server_close()

    def test_real_state_decisions_no_duplicate_submit(self):
        page=Path(app.__file__).with_name('ui-v2.html').read_text()
        fn=page[page.index('function chooseState'):page.index('async function call')]
        cases=[({'pause_requested':True,'summary':{'total_videos':3,'uncertain':1,'not_submitted':2}},'paused'),({'summary':{'total_videos':3,'uncertain':1,'persisted_task_ids':1,'reason':'user_pause'}},'paused'),({'summary':{'total_videos':3,'not_submitted':2,'ready_audio':3,'reason':'budget_limit'}},'ready'),({'summary':{'total_videos':3,'persisted_task_ids':1,'downloaded':0,'not_submitted':2,'reason':'budget_limit'},'outstanding_results':1},'collect'),({},'prepare'),({'busy':True},'busy'),({'summary':{'total_videos':3,'uncertain':1}},'ready'),({'summary':{'total_videos':3,'persisted_task_ids':3,'downloaded':0,'paused':True,'reason':'collect_interrupted_keep_task_ids'}},'collect'),({'summary':{'total_videos':3,'persisted_task_ids':3,'downloaded':0,'reason':'authentication_error'}},'blocked'),({'summary':{'total_videos':3,'not_submitted':3,'ready_audio':3}},'ready'),({'results_ready':True,'summary':{'total_videos':3,'persisted_task_ids':3,'downloaded':3}},'done'),({'summary':{'total_videos':3,'reason':'user_pause'}},'paused'),({'summary':{'total_videos':3,'persisted_task_ids':3,'failed':3},'outstanding_results':0},'blocked')]
        script=fn+'\nconst cases='+json.dumps(cases)+';for(const [input,want] of cases){const state=chooseState(input);if(state.name!==want)throw Error(JSON.stringify({input,state,want}));if(want==="collect"&&state.op!=="collect")throw Error("must not submit")}';subprocess.run(['node','-e',script],check=True)
    def test_no_secret_storage_or_external_assets(self):
        page=Path(app.__file__).with_name('ui-v2.html').read_text()
        for bad in ['localStorage','sessionStorage','indexedDB','src="http','href="http']:
            self.assertNotIn(bad,page)
        self.assertIn('type="password"',page);self.assertIn('role="alert"',page);self.assertIn('focus-visible',page)
        self.assertIn("el('origin').disabled=d.origin_bound===true||d.busy",page)
        self.assertIn("d.origin_bound===false",page)

    def test_budget_excess_is_visible_before_key_or_network(self):
        page=app.PAGE.read_text()
        fn=page[page.index('async function action(op)'):page.index("el('choose-source').onclick")]
        setup="""let requestBusy=false,latest={session_cap_yuan:0.75};
const fields={root:{value:'/synthetic'},work:{value:'/synthetic-work'},'new-output':{checked:false},key:{value:'NOT-A-REAL-KEY'},authorized:{checked:true},budget:{value:'2',focus(){}},error:{}};
const el=id=>fields[id];function call(){throw Error('network forbidden')}function refresh(){}function render(){}
"""
        script=setup+fn+";action('run').then(()=>{if(fields.error.hidden!==false||!fields.error.textContent.includes('0.75'))throw Error('error not visible');if(fields.key.value!=='NOT-A-REAL-KEY')throw Error('key unnecessarily cleared');});"
        subprocess.run(['node','-e',script],check=True)
