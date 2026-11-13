"""Two-stage bounded batch. Only an interactive human can supply ephemeral credentials."""
import argparse,concurrent.futures,copy,hashlib,json,math,os,signal,subprocess,sys,threading,time,urllib.parse
from pathlib import Path
import aliyun_sample as a
import aliyun_live as live
import videolib as v
import batch_paths as paths
import workflow_state as workflow
from aliyun_review_html import render
BASE=Path(__file__).resolve().parent
TOOLS=BASE
WORK=paths.task_directory(BASE)
CONFIG={'model':'fun-asr','language_hints':['zh'],'diarization_enabled':True,'channel_id':[0],'audio':'16k-mono-pcm-full-timeline','adapter':1}

class Store:
    def __init__(self,path,backup=True):
        self.path=Path(path);self.lock=threading.RLock();self.data=v.load(self.path);self.root=Path(self.data['root']).resolve(strict=True);self.backup=backup;self.output_root=Path(self.data.get('output_root',self.path.parent.parent/'deliverables')).resolve()
        if self.data.get('output_identity'):
            raw_output=Path(self.data['output_root'])
            if raw_output.is_symlink():raise ValueError('导出目录被替换为符号链接，停止写入')
            ost=raw_output.stat()
            if [ost.st_dev,ost.st_ino]!=self.data['output_identity']:raise ValueError('导出目录身份改变，停止写入')
        self.stop=threading.Event();self.journal=self.path.parent/'.pending-state.json';self.recovery_required=self.journal.exists() or self.has_unmerged_receipts()
    def response_receipts(self):
        directory=self.path.parent/'response-receipts'
        if directory.is_symlink():raise ValueError('Response receipt directory cannot be a symlink')
        return [v.load(p) for p in sorted(directory.glob('*.json'))] if directory.exists() else []
    def has_unmerged_receipts(self):
        for receipt in self.response_receipts():
            job=self.data.get('jobs',{}).get(receipt['job_id'],{})
            attempts=job.get('attempt_history',[])
            if not any(x.get('number')==receipt['attempt_number'] and x.get('task_id')==receipt['task_id'] for x in attempts):return True
        return False
    def persist_response(self,ident,number,task_id):
        # Independent append-only inbox: writable even when aggregate receipts need repair.
        directory=self.path.parent/'response-receipts'
        if directory.is_symlink():raise ValueError('Response receipt directory cannot be a symlink')
        directory.mkdir(exist_ok=True)
        target=directory/(hashlib.sha256((ident+':'+str(number)).encode()).hexdigest()+'.json')
        receipt={'schema':1,'job_id':ident,'attempt_number':number,'task_id':task_id}
        if target.exists():
            if v.load(target)!=receipt:raise ValueError('Conflicting response receipt')
            return
        v.atomic_json(target,receipt)
    def merge_response_receipts(self,payload):
        for receipt in self.response_receipts():
            ident=receipt['job_id'];number=receipt['attempt_number'];task_id=receipt['task_id']
            if ident not in payload['jobs'] or not isinstance(number,int) or not isinstance(task_id,str) or not a.re.fullmatch(r'[A-Za-z0-9-]{1,100}',task_id):raise ValueError('Invalid response receipt')
            job=payload['jobs'][ident]
            attempt=next((x for x in job.get('attempt_history',[]) if x.get('number')==number),None)
            if attempt is None:raise ValueError('Response receipt has no reserved attempt')
            if attempt.get('task_id')==task_id:continue
            workflow.record_id(job,number,task_id)
    def disk(self):
        if self.recovery_required:raise ValueError('任务回执需恢复核对，禁止继续提交')
        paths.validate_export(self.data)
        try:
            s=self.root.stat()
            if [s.st_dev,s.st_ino]!=self.data['root_identity']:raise OSError('identity changed')
        except OSError:
            self.stop.set();self.data.update(paused=True,reason='disk_missing_or_changed');v.atomic_json(self.path,self.data)
            raise ValueError('硬盘失联/身份改变；停止新提交，不创建挂载目录') from None
    def save(self):
        with self.lock:
            if self.recovery_required:raise ValueError('任务回执需恢复核对，禁止覆盖未完成事务')
            self.data['state_revision']=self.data.get('state_revision',0)+1
            snapshot=copy.deepcopy(self.data)
            encoded=json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()
            v.atomic_json(self.journal,{'schema':1,'sha256':hashlib.sha256(encoded).hexdigest(),'payload':snapshot})
            try:
                v.atomic_json(self.path,snapshot)
                if self.backup:
                    self.disk();backup=self.output_root/'转写结果'/paths.receipt_name(snapshot)
                    if not backup.parent.resolve().is_relative_to(self.output_root):raise ValueError('备份路径越界')
                    backup.parent.mkdir(parents=True,exist_ok=True);v.atomic_json(backup,snapshot)
                    if v.load(self.path)!=v.load(backup):raise ValueError('写后回执不一致')
                self.journal.unlink()
            except (ValueError,OSError):
                self.stop.set();self.recovery_required=True
                raise ValueError('任务清单双写未完成；保留恢复日志，停止提交') from None
    def repair_receipts(self):
        if not self.recovery_required:return
        payload=copy.deepcopy(self.data)
        if self.journal.exists():
            record=v.load(self.journal);payload=record['payload']
            expected=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if record.get('sha256')!=expected:raise ValueError('恢复日志校验失败')
            if payload.get('root')!=self.data.get('root') or payload.get('output_root')!=self.data.get('output_root'):raise ValueError('恢复日志批次不匹配')
            if self.data.get('state_revision',0)>payload.get('state_revision',0):raise ValueError('当前状态比恢复日志更新，拒绝回滚')
        self.merge_response_receipts(payload)
        self.recovery_required=False
        try:
            self.disk();payload=copy.deepcopy(payload)
            previous_reason=payload.get('reason')
            payload.setdefault('receipt_repair_history',[]).append({'at':time.time(),'previous_reason':previous_reason})
            payload.update(paused=True,reason=previous_reason or 'user_pause')
            self.data=payload;self.save();self.stop.clear()
        except BaseException:
            self.recovery_required=True;raise
    def pause(self,reason):
        with self.lock:
            if reason=='user_pause' and self.data.get('reason') not in (None,'user_pause'):reason=self.data['reason']
            self.stop.set();self.data.update(paused=True,reason=reason)
            try:self.save()
            except (OSError,ValueError):pass
        print('已暂停新提交：'+reason,flush=True)
    def summary(self):
        jobs=list(self.data['jobs'].values())
        return {'total_videos':len(jobs),'probe_failed':sum(j['status']=='probe_failed' for j in jobs),'audio_total':sum(j['status'] not in ('no_audio','probe_failed') for j in jobs),'persisted_task_ids':sum(bool(j.get('task_id')) for j in jobs),
                'ready_audio':sum(bool(j.get('audio_path')) for j in jobs),'no_audio':sum(j['status']=='no_audio' for j in jobs),
                'not_submitted':sum(j['status'] in ('pending','audio_missing') for j in jobs),
                'historical_uncertain_attempts':sum(sum(not x.get('task_id') and x.get('status')=='submission_uncertain' for x in j.get('attempt_history',[])) for j in jobs),'uncertain':sum(j['status']=='submission_uncertain' for j in jobs),'failed':sum(j['status'] in ('failed','upload_failed') for j in jobs),
                'downloaded':sum(j['status'] in ('downloaded','exported') for j in jobs),'reused':sum(j.get('reused',False) for j in jobs),
                'no_words':sum(j.get('recognition_outcome')=='no_recognized_words' and j['status']=='exported' for j in jobs),'with_words':sum(j.get('recognition_outcome')!='no_recognized_words' and j['status']=='exported' for j in jobs),'retry_eligible':sum(workflow.retry_eligible(self.data,j) for j in jobs),'paused':self.data['paused'] or self.recovery_required,'reason':'receipt_recovery_required' if self.recovery_required else self.data.get('reason'),'reserved_yuan':self.data['reserved_microyuan']/1e6}

def require_resume_allowed(store):
    if store.data.get('reason') not in (None,'user_pause'):
        raise ValueError('此前非用户暂停原因尚未解决，保留状态，禁止自动解除')

def source_check(store,job):
    store.disk();path=(store.root/job['relative_path']).resolve(strict=True)
    if not path.is_relative_to(store.root) or not path.is_file():raise ValueError('源路径越界或缺失')
    s=path.stat()
    if s.st_size!=job['source']['size'] or s.st_mtime_ns!=job['source']['mtime_ns']:raise ValueError('源指纹变化，停止复用或提交')

def prepare(path):
    path=Path(path)
    if (path.parent/'.pending-state.json').exists() or (path.exists() and Store(path).recovery_required):raise ValueError('任务回执需恢复核对，禁止重新准备')
    if (WORK/'runner.lock').exists():raise ValueError('批量会话正在运行，禁止并行重建清单')
    index=next((BASE/'production-output').glob('*/index/library.json'));library=v.load(index);root=Path(library['root']).resolve(strict=True);st=root.stat()
    audio=v.load(BASE/'audio-preparation'/'inventory.json',{});ready={r['id']:r for r in audio.get('rows',[]) if r['status']=='ready'}
    previous=v.load(path,{})
    if previous and previous.get('root_identity')!=[st.st_dev,st.st_ino]:raise ValueError('硬盘身份改变，停止准备')
    jobs=previous.get('jobs',{});old_config=previous.get('config')
    if old_config and old_config!=CONFIG:raise ValueError('参数改变，需独立任务清单')
    for row in library['videos']:
        rel=row['relative_path']
        if Path(rel).name.startswith('._') or rel.split('/')[0] in ('转写结果','转写结果明细'):continue
        ident=row['id'];fingerprint=v.key(json.dumps({'root_id':library['root_id'],'source':row.get('source',{}),'relative_path':rel,'config':CONFIG},sort_keys=True))
        if ident in jobs and jobs[ident]['fingerprint']!=fingerprint:raise ValueError('源或参数改变，需新任务版本')
        job=jobs.setdefault(ident,{'id':ident,'relative_path':rel,'source':row.get('source',{}),'fingerprint':fingerprint,'status':'audio_missing'})
        media=row.get('media_info',{})
        if media.get('has_audio') is False:job['status']='no_audio';continue
        if media.get('has_audio') is not True or media.get('duration_seconds') is None:job.update(status='probe_failed',failure_reason='source_metadata_unknown');continue
        job['expected_seconds']=media['duration_seconds']
        candidates=[]
        if ident in ready:candidates.append(Path(ready[ident]['audio_path']))
        prep=BASE/'audio-preparation'/'audio'/f'{ident}.wav';manifest=v.load(BASE/'audio-preparation'/'manifests'/f'{ident}.json',{})
        if manifest.get('source')==row['source'] and manifest.get('status')=='ready':candidates.append(prep)
        for candidate in candidates:
            if candidate.is_file():
                from prepare_audio import wav_info
                info=wav_info(candidate,job['expected_seconds'])
                job.update(audio_path=str(candidate),duration_seconds=info['duration_seconds'],audio_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
                if job['status']=='audio_missing':job['status']='pending'
                break
    data={**previous,'schema':1,'root':str(root),'root_identity':[st.st_dev,st.st_ino],'config':CONFIG,'jobs':jobs,'paused':previous.get('paused',False),'reserved_microyuan':previous.get('reserved_microyuan',0),'budget_microyuan':previous.get('budget_microyuan',0),'free_only':previous.get('free_only',True)}
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():v.atomic_json(path,data)
    store=Store(path);store.data=data;store.save();print(json.dumps(store.summary(),ensure_ascii=False),flush=True)
    return store

def _submit_one_attempt(store,api,ident,upload=live.upload):
    job=store.data['jobs'][ident]
    if (store.path.parent.parent/'pause.request').exists():store.stop.set();return
    stage='source_check'
    try:
        source_check(store,job)
        audio=Path(job['audio_path'])
        if hashlib.sha256(audio.read_bytes()).hexdigest()!=job['audio_sha256']:raise ValueError('音轨缓存指纹不符')
        if store.stop.is_set():return
        if store.data.get('price_microyuan_per_second',0)<=0 or store.data.get('budget_microyuan',0)<=0:raise ValueError('本批价格与预算尚未授权')
        charge=math.ceil(job['duration_seconds']*store.data['price_microyuan_per_second'])
        if store.data['reserved_microyuan']+charge>store.data['budget_microyuan']:store.pause('budget_limit');return
        stage='upload'
        for attempt in range(3):
            try:temporary=upload(api,audio);break
            except (a.NetworkFailure,a.ProviderError) as exc:
                retryable=isinstance(exc,a.NetworkFailure) or exc.status in (429,500,502,503,504)
                if not retryable or attempt==2:raise
                if store.stop.is_set():return
                time.sleep(2**attempt)
        with store.lock:
            if (store.path.parent.parent/'pause.request').exists():store.stop.set();return
            if store.stop.is_set() or store.data['paused']:return
            charge=math.ceil(job['duration_seconds']*store.data['price_microyuan_per_second']) # 0.00022 yuan/s, no free discount assumed.
            if store.data['reserved_microyuan']+charge>store.data['budget_microyuan']:
                store.pause('budget_limit');return
            attempt_number=workflow.reserve_attempt(store.data,job,charge)
            store.save() # Intent and budget durable in both destinations before POST.
        stage='submit'
        response=api.submit(temporary,official_upload_verified=True);temporary=None
        task_id=response.get('output',{}).get('task_id')
        if not isinstance(task_id,str) or not a.re.fullmatch(r'[A-Za-z0-9-]{1,100}',task_id):raise ValueError('没有有效任务ID')
        with store.lock:
            store.persist_response(ident,attempt_number,task_id)
            workflow.record_id(job,attempt_number,task_id);store.save()
            print(json.dumps(store.summary(),ensure_ascii=False),flush=True)
    except a.NetworkFailure as e:
        # Upload attempts cannot create an ASR task. POST ambiguity is isolated and charged.
        with store.lock:
            job['submission_diagnostic']={'stage':stage,'exception_type':type(e).__name__,'network_kind':e.kind,'at':time.time()}
            if stage=='upload':
                job['upload_failure']=True
                if job['status']!='submission_uncertain':job['status']='upload_failed'
            store.save()
        print('单条网络异常已隔离；其他未提交任务继续，未知POST不重投。',flush=True)
    except a.ProviderError as e:
        if e.status in (429,500,502,503,504):
            with store.lock:
                job['submission_diagnostic']={'stage':stage,'exception_type':'ProviderError','http_status':e.status,'at':time.time()}
                if stage=='upload':
                    job['upload_failure']=True
                    if job['status']!='submission_uncertain':job['status']='upload_failed'
                store.save()
            return
        code=e.code
        reason='quota_or_balance_exhausted' if any(x in code.lower() for x in ('allocationquota','freetieronly','balance','arrear','quota')) else ('authentication_error' if e.status in (401,403) else 'provider_error')
        store.pause(reason)
    except (OSError,ValueError) as e:
        # Any POST ambiguity stays uncertain; no automatic retry. Upload failures also pause.
        if stage=='submit' and isinstance(e,ValueError) and str(e)=='没有有效任务ID':
            with store.lock:
                job['submission_diagnostic']={'stage':stage,'exception_type':'InvalidTaskID','at':time.time()};store.save()
        else:store.pause('network_disk_or_submission_uncertain')
        print('单条请求异常；未回显输入或凭据。',flush=True)

def submit_one(store,api,ident,upload=live.upload):
    job=store.data['jobs'][ident]
    while not store.stop.is_set():
        if job['status']!='pending' and not workflow.retry_eligible(store.data,job):return
        _submit_one_attempt(store,api,ident,upload)
        if store.stop.is_set() or store.data.get('paused') or job.get('upload_failure') or not workflow.retry_eligible(store.data,job):return
        if (store.path.parent.parent/'pause.request').exists():return
        time.sleep(1)

def resume_independent_pending(store):
    store.disk()
    if store.data.get('reason') not in (None,'user_pause','network_disk_or_submission_uncertain','collect_interrupted_keep_task_ids','failed_detail_query_interrupted','failed_detail_query_http_error'):
        raise ValueError('此故障不是可隔离的网络提交问题，不能续跑')
    if (store.path.parent.parent/'pause.request').exists():raise ValueError('用户暂停请求仍有效')
    jobs=list(store.data['jobs'].values())
    for job in jobs:
        if job['status']=='submitted' and not job.get('task_id'):raise ValueError('已提交任务缺ID')
        if job['status']=='submission_uncertain' and (job.get('task_id') or job.get('reserved_microyuan',0)<=0):raise ValueError('未知任务费用或ID记录异常')
    allocated=sum(j.get('reserved_microyuan',0) for j in jobs)
    if allocated!=store.data['reserved_microyuan']:raise ValueError('费用记录不一致，不能续跑')
    if not 0<store.data['budget_microyuan']<=store.data.get('approved_spending_cap_microyuan',store.data['budget_microyuan']):raise ValueError('预算授权异常')
    if allocated>store.data['budget_microyuan']:raise ValueError('历史预留已超预算')
    # Persist the old reason in history; only the queue pause is released.
    store.data.setdefault('recovery_history',[]).append({'at':time.time(),'previous_reason':store.data.get('reason'),'action':'continue_only_pending_preserve_unknown_ids_and_cost'})
    store.data.update(paused=False,reason=None);store.stop.clear();store.save()

def submit_all(store,api,upload=live.upload,follow_audio=False):
    pending=iter(j['id'] for j in store.data['jobs'].values() if j['status']=='pending' or workflow.retry_eligible(store.data,j))
    # Reserve only three actual upload/POST windows; remote RUNNING tasks don't block new slots.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        active=set()
        while not store.stop.is_set():
            while len(active)<3:
                ident=next(pending,None)
                if ident is None:break
                active.add(pool.submit(submit_one,store,api,ident,upload))
            if not active:
                if not follow_audio:break
                refreshed=0
                for job in store.data['jobs'].values():
                    if job['status']!='audio_missing':continue
                    manifest=v.load(BASE/'audio-preparation'/'manifests'/(job['id']+'.json'),{})
                    if manifest.get('status')=='ready' and manifest.get('source')==job['source']:
                        audio=Path(manifest['audio_path']);source_check(store,job)
                        from prepare_audio import wav_info
                        info=wav_info(audio,job['expected_seconds'])
                        job.update(status='pending',audio_path=str(audio),duration_seconds=info['duration_seconds'],audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest());refreshed+=1
                if refreshed:
                    store.save();pending=iter(j['id'] for j in store.data['jobs'].values() if j['status']=='pending');continue
                extraction=v.load(BASE/'audio-preparation'/'progress.json',{})
                if extraction.get('status')!='extracting':break
                print('等待本地提取新音轨；现有ID已保存。',flush=True);time.sleep(5);continue
            done,active=concurrent.futures.wait(active,timeout=1,return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:future.result()
    if hasattr(store,'path') and (store.path.parent.parent/'pause.request').exists() and store.data.get('reason') in (None,'user_pause'):store.pause('user_pause')
    print('阶段1结束；只有全部待识别音轨均取得持久化ID或成功复用，才算提交完成。',flush=True)
    print(json.dumps(store.summary(),ensure_ascii=False),flush=True)

def export_job(store,job):
    source_check(store,job);directory=Path(job['result_dir']);doc=v.load(directory/'normalized.json');turns=v.load(directory/'turns.json')
    version=hashlib.sha256(json.dumps({'exporter':'word-html-v2','source':job['source'],'audio_sha256':job.get('audio_sha256'),'normalized_sha256':v.digest(directory/'normalized.json'),'turns_sha256':v.digest(directory/'turns.json')},sort_keys=True).encode()).hexdigest()
    rel=Path(job['relative_path']);detail=store.output_root/'转写结果'/paths.detail_name(store.data)/rel.parent/(rel.name+'.结果');word=store.output_root/'转写结果明细'/rel.with_suffix('.docx')
    for path in (detail,word):
        if not path.resolve().is_relative_to(store.output_root):raise ValueError('导出路径越界')
    detail.mkdir(parents=True,exist_ok=True)
    for name in ['raw-response.json','normalized.json','turns.json','逐句稿.txt','时间码.txt','字幕.srt','发言段采访稿.txt']:
        content=(directory/name).read_bytes();target=detail/name
        if target.exists() and target.read_bytes()!=content:raise ValueError('已有不同文件，拒绝覆盖')
        if not target.exists():target.write_bytes(content)
    video=v.local_media_url(store.root/rel,detail)
    page=render({'video':video,'segments':doc['segments'],'turns':turns,'title':rel.name,'duration_seconds':job['duration_seconds']})
    if doc.get('recognition_outcome')=='no_recognized_words':page=page.replace('</body>','<p>本段服务未识别出文字。此说明不是对白转写，也不表示已确认视频中无人说话。</p></body>')
    target=detail/'核对.html'
    if target.exists() and target.read_text(encoding='utf-8')!=page:raise ValueError('已有HTML版本或内容不同，保留旧稿')
    if not target.exists():target.write_text(page,encoding='utf-8')
    if not word.exists():
        python=sys.executable
        subprocess.run([str(python),str(TOOLS/'export_interview_docx.py'),'--source',str(directory),'--output',str(word)],check=True)
    else:
        receipt=job.get('export_receipt',{})
        if receipt.get('version')!=version or receipt.get('word_sha256')!=v.digest(word):raise ValueError('已有Word缺少匹配版本/校验记录，保留并停止复用')
        from docx import Document
        if not any(p.text=='来源：'+job['relative_path'] for p in Document(word).paragraphs):raise ValueError('同名Word来源冲突，保留并报告')
    job['export_receipt']={'version':version,'word_relative_path':str(word.relative_to(store.output_root)),'word_sha256':v.digest(word),'html_sha256':v.digest(target)}
    job.pop('export_deferred',None);job.pop('collection_deferred',None);job['status']='exported';store.save()

def diagnostic_text(value):
    if not isinstance(value,str):return ''
    value=a.re.sub(r'(?i)(?:https?|oss)://[^\s<>\"\']+', '[URL redacted]',value)
    value=a.re.sub(r'(?i)bearer\s+\S+', '[authorization redacted]',value)
    value=a.re.sub(r'\bsk[^\s<>\"\']*', '[credential redacted]',value)
    value=a.re.sub(r'(?i)(signature|policy|authorization|accesskey|api[_-]?key)\s*[:=]\s*[^\s,;]+',r'\1=[redacted]',value)
    return ''.join(c for c in value if c in '\n\t' or ord(c)>=32)[:1000]

def failure_evidence(response):
    out=response.get('output',{})
    def fields(node):
        return {k:diagnostic_text(node.get(k)) for k in ('code','message','request_id') if isinstance(node.get(k),str)}
    result={'task_status':diagnostic_text(out.get('task_status')),'request':fields(response),'output':fields(out),
            'subtasks':[{'subtask_status':diagnostic_text(item.get('subtask_status')),**fields(item)} for item in out.get('results',[]) if isinstance(item,dict)],'queried_at':time.time()}
    return result

def export_no_words(store,job,evidence):
    if evidence.get('output',{}).get('code')!='ASR_RESPONSE_HAVE_NO_WORDS':raise ValueError('没有厂商无文字证据')
    directory=WORK/'results'/job['id'];directory.mkdir(parents=True,exist_ok=True)
    if (directory/'normalized.json').exists() and v.load(directory/'normalized.json').get('segments'):raise ValueError('已有非空文字结果，拒绝改为空稿')
    raw={'record_type':'no_words_document_from_provider_evidence','provider_evidence':evidence,'transcripts':[]}
    live.export(raw,{'sample_id':job['id'],'source_relative_path':job['relative_path'],'offset_seconds':0,'duration_seconds':job['duration_seconds']},directory)
    normalized=v.load(directory/'normalized.json');normalized['recognition_outcome']='no_recognized_words';v.atomic_json(directory/'normalized.json',normalized)
    (directory/'发言段采访稿.txt').write_text('本段服务未识别出文字。此说明不是对白转写，也不表示已确认视频中无人说话。\n',encoding='utf-8')
    job.update(status='downloaded',result_dir=str(directory),recognition_outcome='no_recognized_words',provider_no_words_evidence=evidence)
    store.save();export_job(store,job)

def record_failure(store,job,response,reason):
    evidence=failure_evidence(response)
    directory=WORK/'task-diagnostics';directory.mkdir(parents=True,exist_ok=True)
    v.atomic_json(directory/(job['id']+'.json'),{'task_id':job['task_id'],'relative_path':job['relative_path'],'duration_seconds':job['duration_seconds'],'diagnostic':evidence})
    job.pop('collection_deferred',None);job.update(status='failed',failure_reason=reason,failure_diagnostic=evidence);store.save()
    if evidence.get('output',{}).get('code')=='ASR_RESPONSE_HAVE_NO_WORDS':export_no_words(store,job,evidence)

def collect(store,api,download=None,export=True,wait=False):
    if download is None:download=lambda url:json.loads(live.safe_open(urllib.request.Request(live.oss_endpoint(url)),16_000_000))
    print('开始查询已有任务；不会上传或提交新识别。网络请求超时上限30秒。',flush=True)
    if store.data.get('reason')=='collect_interrupted_keep_task_ids':
        store.disk()
        if any(j['status']=='submitted' and not j.get('task_id') for j in store.data['jobs'].values()):
            raise ValueError('已提交任务缺ID，保留清单')
        store.data.update(paused=False,reason=None);store.save()
    diagnosed_now=0;query_deferred=set();deferred_round=0
    while True:
        waiting=0
        for job in store.data['jobs'].values():
            if job['id'] in query_deferred:continue
            if (store.path.parent.parent/'pause.request').exists():
                if store.data.get('reason') in (None,'user_pause'):store.pause('user_pause')
                return
            if store.stop.is_set():return
            if job['status']=='failed' and not job.get('failure_diagnostic'):
                try:
                    if diagnosed_now%10==0:print(f'正在补查失败详情：本轮完成{diagnosed_now}条；任务 {job["task_id"]}…',flush=True)
                    result=api.task(job['task_id']) # GET only: inspect historical failures, never POST.
                    record_failure(store,job,result,job.get('failure_reason','cloud_failed_inspected'))
                    diagnosed_now+=1
                except (a.ProviderError,OSError,ValueError) as exc:
                    job['collection_diagnostic']={'stage':'failed_task_query','exception_type':type(exc).__name__,'at':time.time()}
                    job['collection_deferred']=True;query_deferred.add(job['id']);store.save()
                    if isinstance(exc,a.ProviderError) and exc.status in (401,403):store.pause('authentication_error');return
                continue
            if job['status']=='submitted':
                stage='task_query'
                try:
                    result=api.task(job['task_id']);job.pop('collection_deferred',None);out=result.get('output',{});status=out.get('task_status')
                    if status in ('PENDING','RUNNING'):waiting+=1;continue
                    if status=='SUCCEEDED':
                        items=out.get('results',[])
                        if len(items)!=1 or items[0].get('subtask_status')!='SUCCEEDED':
                            record_failure(store,job,result,'subtask_failed_under_SUCCEEDED');continue
                        stage='result_download'
                        raw=download(items[0]['transcription_url']);directory=WORK/'results'/job['id'];directory.mkdir(parents=True,exist_ok=True)
                        # Persist real response immediately, before any conversion/export.
                        v.atomic_json(directory/'raw-response.json',live.safe_result(raw))
                        sample={'sample_id':job['id'],'source_relative_path':job['relative_path'],'offset_seconds':0,'duration_seconds':job['duration_seconds']}
                        stage='result_conversion'
                        live.export(raw,sample,directory);job.update(status='downloaded',result_dir=str(directory),downloaded_at=time.time());store.save()
                    elif status in ('FAILED','CANCELED'):record_failure(store,job,result,'cloud_'+status)
                    else:raise ValueError('未知状态')
                except (a.ProviderError,OSError,ValueError) as exc:
                    # Never persist exception text: it may contain signed URLs or credentials.
                    evidence={'stage':stage,'exception_type':type(exc).__name__,'at':time.time()}
                    http_status=getattr(exc,'status',None)
                    if isinstance(http_status,int):evidence['http_status']=http_status
                    code=getattr(exc,'code',None)
                    if isinstance(code,int):evidence['http_status']=code
                    elif isinstance(code,str) and code in ('InvalidApiKey','AccessDenied','Unauthorized','InvalidParameter','Throttling'):evidence['provider_code']=code
                    known=('只允许官方北京OSS HTTPS地址','OSS请求失败；不自动重试，不回显签名','未知状态')
                    if str(exc) in known:evidence['detail']=str(exc)
                    job['collection_diagnostic']=evidence
                    job['collection_deferred']=True;query_deferred.add(job['id']);store.save()
                    if isinstance(exc,a.ProviderError) and exc.status in (401,403):store.pause('authentication_error');return
                    continue
            if export and job['status']=='downloaded':
                try:export_job(store,job)
                except (ValueError,OSError,subprocess.CalledProcessError):
                    job['export_deferred']=True;query_deferred.add(job['id']);store.save();continue
        print(json.dumps(store.summary(),ensure_ascii=False),flush=True)
        if not wait:return
        if store.stop.is_set():return
        if query_deferred and deferred_round<2:
            deferred_round+=1;query_deferred.clear();time.sleep(2**deferred_round);continue
        if not waiting:return
        time.sleep(5)

import urllib.request

def acquire_runner_lock(path,mode):
    try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise ValueError('存在运行锁；先核实进程，不能直接删除。请保留此窗口并报告锁冲突') from None
    try:
        try:started=subprocess.run(['ps','-p',str(os.getpid()),'-o','lstart='],capture_output=True,text=True).stdout.strip() if os.name!='nt' else 'not_available_on_windows'
        except OSError:started='unavailable; never auto-remove lock'
        record={'pid':os.getpid(),'process_start':started,'created_at':time.time(),'mode':mode,'script':str(Path(__file__).resolve())}
        with os.fdopen(fd,'w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
    except BaseException:
        try:os.close(fd)
        except OSError:pass
        path.unlink(missing_ok=True);raise

def release_runner_lock(path):
    if not path.exists():return
    try:record=json.loads(path.read_text())
    except (OSError,ValueError):return
    if record.get('pid')==os.getpid():path.unlink(missing_ok=True)

