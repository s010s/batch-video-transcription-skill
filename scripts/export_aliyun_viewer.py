"""Offline three-column viewer using Aliyun-only data. No cloud calls or sidecars."""
import collections,json,os,time,urllib.parse,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
import videolib as v
import batch_paths as paths
from aliyun_sample import merge_turns
BASE=Path(__file__).resolve().parent
TOOLS=BASE

def relative_file_url(path,destination):
    return v.local_media_url(path,destination)

def existing_word_url(output_root,destination,relative):
    root=output_root
    word=root/'转写结果明细'/relative.with_suffix('.docx')
    if not word.is_file():return None
    resolved=word.resolve(strict=True)
    if word.is_symlink() or not resolved.is_relative_to((root/'转写结果明细').resolve(strict=True)):raise ValueError('Word链接越界')
    with zipfile.ZipFile(word) as z:
        tree=ET.fromstring(z.read('word/document.xml'));ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        first=tree.find('.//w:p',ns)
        if first is None or ''.join(first.itertext())!='来源：'+relative.as_posix():raise ValueError('Word来源与视频不一致')
    return relative_file_url(word,destination)

def build():
    tasks=v.load(paths.task_directory(BASE)/'tasks.json');root=Path(tasks['root']).resolve(strict=True);s=root.stat()
    if [s.st_dev,s.st_ino]!=tasks['root_identity']:raise ValueError('素材硬盘身份改变，停止导出')
    paths.validate_export(tasks)
    output_root=Path(tasks.get('output_root',BASE/'deliverables')).resolve();destination=output_root/'转写结果'
    if destination.is_symlink() or not destination.resolve().is_relative_to(output_root):raise ValueError('结果目录越界')
    videos=[]
    for job in tasks['jobs'].values():
        relative=Path(job['relative_path']);source=(root/relative).resolve(strict=True)
        if relative.is_absolute() or '..' in relative.parts or not source.is_relative_to(root) or not source.is_file():raise ValueError('源视频越界或缺失')
        stamp=source.stat()
        if stamp.st_size!=job['source']['size'] or stamp.st_mtime_ns!=job['source']['mtime_ns']:raise ValueError('源视频改变，停止导出旧文字')
        item={'id':job['id'],'relative_path':relative.as_posix(),'segments':[],'summary':{'status':'not_generated'},'test_data':False}
        if job['status'] in ('exported','downloaded'):
            doc=v.load(Path(job['result_dir'])/'normalized.json')
            assert doc['relative_path']==relative.as_posix()
            turns=merge_turns(doc['segments'])
            recorded=v.load(Path(job['result_dir'])/'turns.json')
            assert [(t['start'],t['end'],t['texts']) for t in turns]==[(t['start'],t['end'],t['texts']) for t in recorded], '发言段与Word来源不一致'
            item.update(status='done' if doc['segments'] else 'no_words',segments=doc['segments'],turns=turns)
            word=existing_word_url(output_root,destination,relative)
            if word:item['word']=word
        elif job['status']=='no_audio':item['status']='no_audio'
        elif job['status'] in ('failed','probe_failed'):
            diag=job.get('failure_diagnostic',{});nodes=[diag.get('request',{}),diag.get('output',{})]+diag.get('subtasks',[])
            codes=[x.get('code') for x in nodes if x.get('code')]
            if any(x in ('ASR_RESPONSE_HAVE_NO_WORDS','SUCCESS_WITH_NO_VALID_FRAGMENT') for x in codes):item.update(status='no_words',provider_error_codes=codes)
            else:item.update(status='failed',error='阿里任务未成功，请查看脱敏诊断记录。')
        else:item.update(status='pending')
        item['media']=relative_file_url(root/relative,destination)
        videos.append(item)
    videos.sort(key=lambda x:x['relative_path'])
    data={'schema':1,'root_name':root.name,'static_export':True,'provider':'aliyun-fun-asr','time_unit':'seconds','updated_at':time.time(),'scan_errors':0,'videos':videos}
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    page=(TOOLS/'web'/'index.html').read_text().replace('/style.css?token=__TOKEN__','style.css').replace('<script defer src="/app.js?token=__TOKEN__"></script>','<script defer src="data.js"></script><script defer src="app.js"></script>')
    page=page.replace('● 仅本机 · 离线处理','● 转写结果 · 硬盘离线浏览').replace('页面每 3 秒刷新处理状态','离线快照 / 随整个素材目录搬移').replace('先在 CLI 指定素材 root 并执行 scan。这里会显示视频与转写状态。','选择左侧素材或搜索视频里说过的话。')
    files={'视频文字稿.html':page,'data.js':'window.VIDEO_LIBRARY = '+payload+';\n','app.js':(TOOLS/'web'/'app.js').read_text(),'style.css':(TOOLS/'web'/'style.css').read_text(),'打开说明.txt':'双击本目录的 视频文字稿.html 可搜索文字与打开Word。请保留data.js、app.js、style.css及同级转写结果明细。\n默认导出位于素材下的独立Transcription-Export子目录，视频链接使用相对路径。将整个素材文件夹（包括全部原视频、导出目录及其内部结构）一起移动，链接仍保持有效；单独移动或改名子目录/视频则需重新导出。\n外部导出目录或Windows跨盘file URI不保证整包移动后播放。视频是否能播放取决于浏览器与原编码；未附带原视频只能阅读文字。\n'}
    local=BASE/('viewer-cache' if paths.neutral(tasks) else 'aliyun-viewer');local.mkdir(exist_ok=True)
    for name,content in files.items():(local/name).write_text(content,encoding='utf-8')
    v.atomic_json(local/'expected-counts.json',dict(collections.Counter(x['status'] for x in videos)))
    return destination,local,files,data

if __name__=='__main__':
    dest,local,files,data=build();warnings=[];ownership=dest/paths.ownership_name(v.load(paths.task_directory(BASE)/'tasks.json'))
    for name,content in files.items():v.guarded_text(dest/name,content,ownership,warnings)
    if warnings:raise ValueError('存在手改/未知同名文件，未覆盖：'+str(warnings))
    print(json.dumps({'entry':str(dest/'视频文字稿.html'),'videos':len(data['videos']),'counts':dict(collections.Counter(x['status'] for x in data['videos'])),'original_video_writes':0,'asr_requests':0},ensure_ascii=False))
