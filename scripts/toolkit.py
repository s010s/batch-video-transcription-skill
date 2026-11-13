#!/usr/bin/env python3
"""Parameterized runner. Local commands never load credentials or call the network."""
import argparse,json,math,signal,sys,time
from decimal import Decimal, InvalidOperation
from pathlib import Path
import videolib as v
import prepare_audio as audio
import aliyun_batch as batch
import aliyun_sample as auth
import export_aliyun_viewer as viewer
import batch_paths as paths

def amount(text):
    try:n=Decimal(text)
    except InvalidOperation:raise ValueError('金额格式无效') from None
    if not n.is_finite() or n<=0:raise ValueError('金额须为有限正数')
    return int((n*1_000_000).to_integral_value(rounding='ROUND_CEILING'))

def configure(work):
    work=Path(work).expanduser().resolve()
    config=v.load(work/'batch.json')
    root=Path(config['root']).resolve(strict=True)
    if not root.is_dir():raise ValueError('素材目录不存在')
    st=root.stat()
    if [st.st_dev,st.st_ino]!=config['root_identity']:raise ValueError('素材目录身份改变')
    audio.BASE=work;audio.CACHE=work/'audio-preparation'
    batch.BASE=work;batch.WORK=paths.task_directory(work);viewer.BASE=work
    return work,root,config

def init(root,work,export_dir=None,include_files=None):
    root=Path(root).expanduser().resolve(strict=True);work=Path(work).expanduser().resolve()
    if not root.is_dir():raise ValueError('素材须为目录')
    if work==root or work.is_relative_to(root) or root.is_relative_to(work):raise ValueError('素材与批次工作目录必须彼此独立')
    if work.exists() and any(work.iterdir()):raise ValueError('批次目录已非空，拒绝覆盖；请使用已有批次的prepare/status')
    selected=None
    if include_files is not None:
        selected=[]
        for item in include_files:
            path=(root/item).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in v.VIDEO_EXT:raise ValueError('限定素材必须是素材目录内的视频')
            selected.append(path.relative_to(root).as_posix())
        selected=sorted(set(selected))
        if not selected:raise ValueError('限定素材清单不能为空')
    # Reserve a fresh export directory; never reuse an existing folder or symlink.
    if export_dir is None:
        output=None
        for index in range(1,1001):
            candidate=root/('Transcription-Export'+('' if index==1 else '-'+str(index)))
            try:candidate.mkdir();output=candidate;break
            except FileExistsError:continue
            except PermissionError:raise ValueError('素材目录只读，无法创建导出子目录；请选择可写的 --export-dir（外部目录不保证整包移动）') from None
        if output is None:raise ValueError('未找到空闲导出目录名')
    else:
        output=Path(export_dir).expanduser().absolute()
        if output==root or root.is_relative_to(output) or output==work or work.is_relative_to(output):raise ValueError('导出目录不能等于或包含素材/工作目录')
        if output.exists() or output.is_symlink():raise ValueError('导出目录已存在，拒绝覆盖')
        if output.parent.resolve()!=output.parent:raise ValueError('导出目录父路径含符号链接，拒绝写入')
        output.mkdir(parents=True,exist_ok=False)
    v.atomic_json(output/'.transcription-export.json',{'schema':1,'kind':'batch-video-transcription-export'})
    ost=output.stat()
    work.mkdir(parents=True,exist_ok=True);st=root.stat()
    v.atomic_json(work/'batch.json',{'schema':1,'root':str(root),'root_identity':[st.st_dev,st.st_ino],'created_at':time.time(),'task_directory':'task-state','selected_sources':selected})
    (work/'task-state').mkdir()
    v.atomic_json(work/'task-state'/'tasks.json',{'schema':1,'root':str(root),'root_identity':[st.st_dev,st.st_ino],'output_root':str(output),'output_identity':[ost.st_dev,ost.st_ino],'output_layout':'neutral-v1','portable_export':output.is_relative_to(root),'jobs':{},'paused':False,'reason':None,'reserved_microyuan':0,'budget_microyuan':0,'price_microyuan_per_second':0,'free_only':True})
    print('独立批次已建立；预算为0；未上传或识别。')

def publish():
    dest,local,files,data=viewer.build();warnings=[]
    for name,content in files.items():v.guarded_text(dest/name,content,dest/paths.ownership_name(v.load(paths.task_directory(viewer.BASE)/'tasks.json')),warnings)
    if warnings:raise ValueError('已有修改或同名文件，未覆盖')
    print(json.dumps({'entry':str(dest/'视频文字稿.html'),'videos':len(data['videos'])},ensure_ascii=False))

def main(argv=None):
    p=argparse.ArgumentParser(description='视频→音频→中文时间码/Word/离线搜索；默认不上传不付费')
    p.add_argument('command',choices=['init','prepare','status','pause','authorize','submit','collect','viewer','merge','repair-receipts'])
    p.add_argument('--work',required=True);p.add_argument('--root');p.add_argument('--budget-yuan');p.add_argument('--price-yuan-per-second');p.add_argument('--upload-authorized',action='store_true');p.add_argument('--paid-authorized',action='store_true');p.add_argument('--wait',action='store_true');p.add_argument('--base-url');p.add_argument('--export-dir');p.add_argument('--include-file',action='append',help='Source-relative video path; repeat to limit a new batch')
    p.add_argument('--accept-duplicate-cost',action='store_true');p.add_argument('--max-unknown-retries',type=int,default=0)
    args=p.parse_args(argv)
    if args.command=='init':
        if not args.root:p.error('init需要 --root')
        init(args.root,args.work,args.export_dir,args.include_file);return
    work,root,config=configure(args.work);path=batch.WORK/'tasks.json'
    if args.command=='status':print(json.dumps(batch.Store(path).summary(),ensure_ascii=False));return
    if args.command=='pause':
        (work/'pause.request').touch();print('已请求暂停新工作；在途请求先保留结果。');return
    # All modifying commands serialize on one per-batch lock.
    lock=work/'operation.lock';batch.acquire_runner_lock(lock,args.command);credential=None
    try:
        store=batch.Store(path) # Read only after acquiring the single-writer lock.
        if args.command=='prepare':
            if (work/'selected-sources.json').exists():raise ValueError('这是限定文件的小样批次；不能自动扩成全目录，请由AI按原选样清单备料。')
            if (work/'pause.request').exists():raise ValueError('已有暂停请求；核实运行结束后才能移除pause.request并继续')
            probe=v.executable(None,'ffprobe')
            if not probe or not v.executable(None,'ffmpeg'):raise ValueError('需要PATH中的ffmpeg和ffprobe')
            library=v.Library(root,work/'production-output');library.scan(probe,include=config.get('selected_sources'))
            report=audio.inventory();audio.Extractor(report).run(2);audio.inventory();batch.prepare(path);return
        if args.command=='viewer':publish();return
        if args.command=='merge':
            import merge_export
            print(json.dumps(merge_export.build(store),ensure_ascii=False));return
        if args.command=='repair-receipts':store.repair_receipts();print('Receipts repaired; batch remains paused.');return
        if args.command=='authorize':
            if not(args.budget_yuan and args.price_yuan_per_second and args.upload_authorized and args.paid_authorized):raise ValueError('须明确本批上传、付费许可、总预算与已核价格；旧授权不继承')
            prior,cap=batch.workflow.budget_context(store.data)
            budget=amount(args.budget_yuan)-prior;price=amount(args.price_yuan_per_second)
            if budget<=0 or (cap is not None and budget>cap):raise ValueError('Total budget exceeds configured cap or leaves no available budget')
            if not 0<=args.max_unknown_retries<=3:raise ValueError('Unknown retries must be 0 to 3')
            if args.max_unknown_retries and not args.accept_duplicate_cost:raise ValueError('Explicit duplicate-charge risk acceptance is required')
            store.data['unknown_retry_policy']={'accept_duplicate_cost':args.accept_duplicate_cost,'max_extra_attempts':args.max_unknown_retries,'authorized_at':time.time()}
            store.data['prior_potential_charge_microyuan']=prior
            if budget<store.data['reserved_microyuan']:raise ValueError('新预算小于已预留费用')
            store.data.update(budget_microyuan=budget,price_microyuan_per_second=price,free_only=False,upload_authorized=True)
            store.data.setdefault('budget_history',[]).append({'at':time.time(),'budget_microyuan':budget,'price_microyuan_per_second':price,'authorization':'explicit new batch flags'})
            if store.data.get('reason')=='budget_limit':store.data.update(paused=False,reason=None)
            store.save();print('已记录本批预算；未读取Key、上传或发起付费请求。');return
        if args.command=='submit':
            if not store.data.get('upload_authorized') or store.data['budget_microyuan']<=0 or store.data.get('price_microyuan_per_second',0)<=0:raise ValueError('本批上传/预算/价格未授权')
            batch.require_resume_allowed(store)
            if (work/'pause.request').exists():raise ValueError('已有暂停请求；先核实旧会话已结束，再移除pause.request')
        if not sys.stdin.isatty():raise ValueError('云端操作须在用户交互终端隐藏输入Key；不接受命令行Key')
        origin=auth.api_origin(args.base_url or store.data.get('api_origin') or auth.DEFAULT_ORIGIN)
        if store.data.get('api_origin') and store.data['api_origin']!=origin:raise ValueError('本批已绑定另一个服务地址，不混用任务。')
        if not store.data.get('api_origin') and any(j.get('task_id') for j in store.data['jobs'].values()) and origin==auth.DEFAULT_ORIGIN:raise ValueError('Existing tasks have no bound origin; specify their original workspace URL')
        store.data['api_origin']=origin;store.save()
        credential=auth.SessionCredential.prompt();api=auth.WorkspaceAPI(origin,credential)
        def stop(*unused):store.pause('user_pause');raise KeyboardInterrupt
        signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
        if args.command=='submit':
            print('将音频上传至阿里云北京官方临时OSS并调用Fun-ASR；按本批预算控制，不保证免费。')
            if input('输入 SUBMIT 确认本批上传与付费：')!='SUBMIT':return
            store.data.update(paused=False,reason=None);store.save();batch.submit_all(store,api)
        else:batch.collect(store,api,wait=args.wait);publish()
    finally:
        if credential:credential.close()
        batch.release_runner_lock(lock)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as e:print('已停止：'+str(e),file=sys.stderr);sys.exit(1)
    except (KeyboardInterrupt,EOFError):print('已停止，任务ID保留，Key未保存。',file=sys.stderr);sys.exit(130)
