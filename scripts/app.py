#!/usr/bin/env python3
"""Local-only helper UI. No Key in CLI, files, logs, URLs, browser storage, or status."""
import argparse,json,math,secrets,threading,webbrowser,datetime
import folder_picker
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import batch_paths as paths
import toolkit as t,aliyun_sample as a,aliyun_batch as b,videolib as v

class AppState:
    def __init__(self,root='',work='',spending_cap=None,prior_charge=None):
        self.picking=False;self.error=None
        self.spending_cap=spending_cap;self.prior_charge=prior_charge
        self.root=str(root);self.work=str(work);self.busy=False;self.message='先准备音轨，不上传、不收费。';self.mutex=threading.Lock()
    def snapshot(self):
        result={'root':self.root,'work':self.work,'busy':self.busy or self.picking,'message':self.message,'error':self.error,'default_origin':a.DEFAULT_ORIGIN,'price':'0.00022','budget_mode':'total','recovery_supported':True,'prior_charge_yuan':(self.prior_charge or 0)/1e6}
        if self.spending_cap is not None:result.update(session_cap_yuan=self.spending_cap/1e6,prior_charge_yuan=(self.prior_charge or 0)/1e6)
        if self.work:
            path=paths.task_directory(self.work)/'tasks.json'
            if path.is_file():
                try:
                    store=b.Store(path);prior,cap=b.workflow.budget_context(store.data,self.prior_charge,self.spending_cap);result['prior_charge_yuan']=prior/1e6
                    if cap is not None:result['session_cap_yuan']=cap/1e6
                    result['retry_policy']=store.data.get('unknown_retry_policy',{})
                    result['origin_bound']=bool(store.data.get('api_origin'));result['origin']=store.data.get('api_origin',a.DEFAULT_ORIGIN);result['summary']=store.summary();result['seconds']=sum(j.get('duration_seconds',0) for j in store.data['jobs'].values());result['estimated_yuan']=sum(math.ceil(j.get('duration_seconds',0)*220) for j in store.data['jobs'].values())/1e6
                    result['entry']=str(store.output_root/'转写结果/视频文字稿.html')
                    result['files']=[{'name':j.get('relative_path',j.get('id','')),'seconds':j.get('duration_seconds',0),'status':j['status']} for j in store.data['jobs'].values()]
                    result['outstanding_results']=sum(j['status'] in ('submitted','downloaded') for j in store.data['jobs'].values())
                    result['exported']=sum(j['status']=='exported' for j in store.data['jobs'].values())
                    result['results_ready']=result['exported']>0 and Path(result['entry']).is_file()
                    result['budget_yuan']=store.data.get('budget_microyuan',0)/1e6
                    result['pause_requested']=(Path(self.work)/'pause.request').exists()
                except (ValueError,OSError,KeyError):result['message']='批次状态暂不可读；保留原文件。'
        return result
    def choose_source(self):
        with self.mutex:
            if self.busy or self.picking:raise ValueError('正在处理任务或选择目录，不能更换素材。')
            if self.work and (Path(self.work)/'batch.json').exists():raise ValueError('当前已有批次；请打开新的空白页面，不修改既有任务。')
            self.picking=True
        try:
            selected=folder_picker.choose_directory()
            if selected is None:return {'cancelled':True}
            # Reserve a name only. The explicit Prepare click creates directories.
            stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
            work=Path.home()/'Documents'/'Video-Transcription-Batches'/stamp
            self.root=str(selected);self.work=str(work)
            self.message='已选择素材。点击准备后仅在本机提取音轨，生成清单供你核对；不上传、不收费。'
            return {'cancelled':False,'root':self.root,'work':self.work,'output_exists':(selected/'Transcription-Export').exists()}
        finally:self.picking=False

    def launch(self,operation,payload):
        # Reserve UI worker before passing any credential to the background operation.
        with self.mutex:
            if self.busy or self.picking:raise ValueError('已有任务或目录选择正在进行，请先完成。')
            if operation not in ('prepare','run','collect','continue-pending','merge','repair-receipts'):raise ValueError('未知操作')
            self.error=None;self.busy=True
        thread=threading.Thread(target=self._execute,args=(operation,payload),daemon=False)
        try:thread.start()
        except BaseException:
            payload.clear();self.busy=False;raise
    def _execute(self,operation,payload):
        credential=None;lock=None;acquired=False
        try:
            root=payload.get('root',self.root);work=payload.get('work',self.work)
            if not root or not work:raise ValueError('请指定素材与独立输出目录。')
            root=str(Path(root).expanduser().resolve(strict=True));work=str(Path(work).expanduser().resolve())
            if operation=='prepare':
                if not (Path(work)/'batch.json').exists():
                    if (Path(root)/'Transcription-Export').exists() and payload.get('output_choice')!='new':raise ValueError('Transcription-Export 已存在。请明确选择另建编号目录，或填写原批次工作目录继续；不会覆盖旧结果。')
                    t.init(root,work)
                _,existing_root,_=t.configure(work)
                if str(existing_root)!=root:raise ValueError('输出目录属于另一批素材；请选择新的输出目录。')
                self.root=root;self.work=work;self.message='正在本地盘点并提取音轨，不上传。'
                t.main(['prepare','--work',work])
                if self.spending_cap is not None or self.prior_charge is not None:
                    caplock=Path(work)/'operation.lock';b.acquire_runner_lock(caplock,'apply-session-cap')
                    try:
                        prepared=b.Store(paths.task_directory(work)/'tasks.json')
                        prior,cap=b.workflow.budget_context(prepared.data,self.prior_charge,self.spending_cap)
                        prepared.data.update(approved_spending_cap_microyuan=cap,prior_potential_charge_microyuan=prior)
                        prepared.save()
                    finally:b.release_runner_lock(caplock)
                self.message='音轨准备完成。核对估价与预算，再输入Key开始识别。';return
            _,existing_root,_=t.configure(work)
            if str(existing_root)!=root:raise ValueError('素材与本批清单不符。')
            self.root=root;self.work=work;lock=Path(work)/'operation.lock';b.acquire_runner_lock(lock,operation);acquired=True
            store=b.Store(paths.task_directory(work)/'tasks.json')
            if operation=='repair-receipts':
                store.repair_receipts();self.message='回执已核对恢复；保持用户暂停，未提交请求。';return
            if operation=='merge':
                import merge_export
                receipt=merge_export.build(store);self.message='合并文稿已生成：'+str(store.output_root/receipt['summary']);return
            if (Path(work)/'pause.request').exists():raise ValueError('存在暂停请求；请让AI核实旧会话和在途结果后恢复。')
            prior,cap=b.workflow.budget_context(store.data,self.prior_charge,self.spending_cap)
            if operation in ('run','continue-pending'):
                if payload.get('authorized') is not True:raise ValueError('请明确同意本批音频上传与预算内付费。')
                budget=t.amount(str(payload.get('total_budget',payload.get('budget',''))))
                if 'total_budget' in payload:
                    budget-=prior
                    if budget<=0:raise ValueError('总预算必须大于历史潜在占用；没有发送新请求')
                if cap is not None and budget>cap:raise ValueError('超过已配置的批准总上限；历史费用不会重置')
                if budget<store.data['reserved_microyuan']:raise ValueError('预算低于已预留费用，不能重置历史用量。')
                allow_retry=payload.get('allow_unknown_retry') is True
                limit=payload.get('unknown_retry_limit',0) if allow_retry else 0
                if not isinstance(limit,int) or isinstance(limit,bool) or not 0<=limit<=3:raise ValueError('额外重试次数必须为0到3的整数')
                store.data['unknown_retry_policy']={'accept_duplicate_cost':allow_retry,'max_extra_attempts':limit,'authorized_at':t.time.time()}
                store.data['prior_potential_charge_microyuan']=prior
                if store.data.get('reason')=='budget_limit' and budget>store.data['budget_microyuan']:
                    store.data.update(paused=False,reason=None)
                store.data['budget_microyuan']=budget
                if operation=='continue-pending':b.resume_independent_pending(store)
                else:b.require_resume_allowed(store)
                if not any(j['status'] in ('pending','submitted','downloaded') or b.workflow.retry_eligible(store.data,j) for j in store.data['jobs'].values()):raise ValueError('没有可执行任务；已完成的不会重做。')
                store.data.update(budget_microyuan=budget,price_microyuan_per_second=220,upload_authorized=True,free_only=False)
                store.data.setdefault('budget_history',[]).append({'at':t.time.time(),'budget_microyuan':budget,'price_microyuan_per_second':220,'authorization':'local UI explicit upload and paid-budget consent'})
                store.save()
            origin=a.api_origin(payload.get('origin') or store.data.get('api_origin') or a.DEFAULT_ORIGIN)
            if store.data.get('api_origin') and store.data['api_origin']!=origin:raise ValueError('服务地址与本批既有记录不同；不可混用空间或重投。')
            if not store.data.get('api_origin') and any(j.get('task_id') for j in store.data['jobs'].values()) and origin==a.DEFAULT_ORIGIN:raise ValueError('旧批次未记录服务地址，请在高级设置填写原业务空间地址；不猜任务所属空间。')
            store.data['api_origin']=origin;store.save()
            credential=a.SessionCredential(payload.pop('key',''));payload.clear();api=a.WorkspaceAPI(origin,credential)
            self.message='正在识别并收取结果；Key仅保留在本次进程内存。'
            if operation=='continue-pending':
                self.message='先查询已有任务，再继续未提交项；未知任务保留隔离，费用继续占用。'
                b.collect(store,api,wait=False)
            if operation in ('run','continue-pending') and not store.stop.is_set():
                store.data.update(paused=False,reason=None);store.save();b.submit_all(store,api)
            if not store.stop.is_set():b.collect(store,api,wait=True)
            t.publish();summary=store.summary()
            self.message='结果已更新。预留费用不等于实际账单；请抽听核对。' if not summary['paused'] else '已暂停：'+str(summary.get('reason'))
            if summary.get('reason')=='collect_interrupted_keep_task_ids':
                evidence=next((j.get('collection_diagnostic') for j in store.data['jobs'].values() if j.get('collection_diagnostic')),None)
                if evidence:self.message+='；'+str(evidence.get('stage'))+' / '+str(evidence.get('exception_type'))+'；任务ID已保留，请仅收集，不重新提交。'
        except Exception as exc:
            self.error=b.diagnostic_text(str(exc)) or '操作未开始，请检查输入与当前批次。'
            self.message='已停止：'+self.error
        finally:
            if credential:credential.close()
            payload.clear()
            if acquired:b.release_runner_lock(lock)
            self.busy=False
    def resume(self):
        with self.mutex:
            if self.busy:raise ValueError('旧任务仍在运行，不能恢复。')
            if not self.work:raise ValueError('尚无批次')
            work=Path(self.work);lock=work/'operation.lock';acquired=False
            try:
                b.acquire_runner_lock(lock,'safe-resume');acquired=True
                store=b.Store(paths.task_directory(work)/'tasks.json');store.disk()
                # User pause only releases scheduling; unknown jobs remain isolated.

                if any(j['status']=='submitted' and not j.get('task_id') for j in store.data['jobs'].values()):raise ValueError('在途任务缺少ID，不能自动恢复。')
                b.require_resume_allowed(store)
                (work/'pause.request').unlink(missing_ok=True)
                store.data.update(paused=False,reason=None);store.save()
                self.message='用户暂停已解除；输入Key后继续，已有任务ID只查询、不重投。'
            finally:
                if acquired:b.release_runner_lock(lock)

    def open_output(self):
        if not self.work:raise ValueError('尚无批次')
        store=b.Store(paths.task_directory(self.work)/'tasks.json')
        entry=store.output_root/'转写结果/视频文字稿.html'
        if not entry.is_file():raise ValueError('尚未生成结果页面')
        webbrowser.open(entry.resolve().as_uri())

    def pause(self):
        if not self.work:raise ValueError('尚无批次')
        (Path(self.work)/'pause.request').touch();self.message='已请求在安全边界暂停，在途任务回执仍保留。'

PAGE=Path(__file__).with_name('ui-v2.html')

def handler_for(state,token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused):pass
        def reply(self,status,data,html=False):
            body=data if html else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def allowed(self,auth=True):
            expected='127.0.0.1:'+str(self.server.server_port)
            if self.headers.get('Host')!=expected:return False
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+expected:return False
            if self.headers.get('Sec-Fetch-Site')=='cross-site':return False
            return not auth or secrets.compare_digest(self.headers.get('X-Local-Token',''),token)
        def do_GET(self):
            if not self.allowed(auth=self.path!='/'):self.reply(403,{'error':'拒绝非本机会话访问'});return
            if self.path=='/':self.reply(200,PAGE.read_bytes(),html=True)
            elif self.path=='/api/status':self.reply(200,state.snapshot())
            else:self.reply(404,{'error':'not found'})
        def do_POST(self):
            payload={}
            try:
                if not self.allowed() or self.headers.get('Origin')!='http://127.0.0.1:'+str(self.server.server_port):self.reply(403,{'error':'拒绝跨站请求'});return
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=32768 or self.headers.get('Content-Type')!='application/json':self.reply(400,{'error':'请求格式错误'});return
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict):raise ValueError('请求格式错误')
                if self.path=='/api/choose-source':self.reply(200,state.choose_source());return
                elif self.path=='/api/pause':state.pause();payload.clear()
                elif self.path=='/api/resume':state.resume();payload.clear()
                elif self.path=='/api/open-output':state.open_output();payload.clear()
                elif self.path in ('/api/prepare','/api/run','/api/collect','/api/continue-pending','/api/merge','/api/repair-receipts'):state.launch(self.path.rsplit('/',1)[-1],payload);payload={}
                else:self.reply(404,{'error':'not found'});return
                self.reply(202,{'accepted':True})
            except (ValueError,TypeError,OSError) as exc:self.reply(400,{'error':b.diagnostic_text(str(exc)) or '操作未开始，请检查状态。'})
            finally:payload.clear()
    return Handler

def main():
    global PAGE
    parser=argparse.ArgumentParser(description='本机视频转写助手，Key不保存')
    parser.add_argument('--root',default='');parser.add_argument('--work',default='');parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--ui-v2',action='store_true',help='Compatibility flag: the state-guided UI is now the default')
    parser.add_argument('--spending-cap-yuan',help='Explicit session spending ceiling; applies to a user-selected new batch')
    parser.add_argument('--prior-charge-yuan',default=None,help='Previously reserved potential charge, shown separately')
    args=parser.parse_args()
    if args.ui_v2:PAGE=Path(__file__).with_name('ui-v2.html')
    state=AppState(args.root,args.work,t.amount(args.spending_cap_yuan) if args.spending_cap_yuan else None,(t.amount(args.prior_charge_yuan) if args.prior_charge_yuan!='0' else 0) if args.prior_charge_yuan is not None else None)
    if args.work and (Path(args.work)/'batch.json').is_file():state.root=v.load(Path(args.work)/'batch.json')['root']
    token=secrets.token_urlsafe(32);server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(state,token))
    url='http://127.0.0.1:'+str(server.server_port)+'/#'+token
    if args.no_open:print('本机页面已启动；为避免泄露会话令牌，不打印访问链接。')
    else:webbrowser.open(url)
    print('本机视频转写助手已启动。浏览器只连本机；关闭此窗口结束服务。')
    try:server.serve_forever()
    except KeyboardInterrupt:
        if state.busy:state.pause()
    finally:server.server_close()

if __name__=='__main__':main()
