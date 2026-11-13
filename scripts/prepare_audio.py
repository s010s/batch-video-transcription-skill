"""Read-only cache inventory and bounded local-only extraction. No ASR/network."""
import argparse,concurrent.futures,hashlib,json,os,signal,subprocess,threading,time,wave
from pathlib import Path
import videolib as v
BASE=Path(__file__).resolve().parent
CACHE=BASE/'audio-preparation'

def wav_info(path,expected):
    with wave.open(str(path)) as w:
        if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2) or w.getnframes()<1:raise ValueError('非有效16k单声道PCM')
        duration=w.getnframes()/16000
        w.setpos(w.getnframes()-1)
        if len(w.readframes(1))!=2:raise ValueError('WAV被截断')
    if abs(duration-expected)>max(2,expected*.01):raise ValueError('音轨时长与源媒体不符')
    return {'duration_seconds':duration,'size_bytes':path.stat().st_size}

def source(root,row):
    path=(root/row['relative_path']).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('来源越界')
    s=path.stat()
    if s.st_size!=row['source']['size'] or s.st_mtime_ns!=row['source']['mtime_ns']:raise ValueError('源文件指纹改变')
    return path

def inventory():
    index=next((BASE/'production-output').glob('*/index/library.json'));library=v.load(index);root=Path(library['root']).resolve(strict=True)
    store=index.parent.parent;rows=[];skips=[];unknown=[]
    for row in library['videos']:
        if row['relative_path'].split('/')[0] in ('转写结果','转写结果明细') or Path(row['relative_path']).name.startswith('._'):continue
        media=row.get('media_info',{})
        if media.get('has_audio') is False:skips.append(row['id']);continue
        if media.get('has_audio') is not True or media.get('duration_seconds') is None:unknown.append(row['id']);continue
        item={'id':row['id'],'relative_path':row['relative_path'],'source':row['source'],'expected_seconds':row['media_info']['duration_seconds'],'status':'missing'}
        try:
            source(root,row)
            candidates=[store/'audio'/f"{row['id']}.wav",CACHE/'audio'/f"{row['id']}.wav"]
            for path in candidates:
                if not path.is_file():continue
                if path.parent.parent==CACHE:
                    manifest=v.load(CACHE/'manifests'/f"{row['id']}.json",{})
                    if manifest.get('source')!=row['source']:continue
                info=wav_info(path,item['expected_seconds'])
                item.update(status='ready',audio_path=str(path),**info);break
        except (OSError,ValueError,wave.Error) as e:item.update(status='invalid',error=str(e))
        rows.append(item)
    CACHE.mkdir(exist_ok=True);report={'root':str(root),'total_audio_videos':len(rows),'ready':sum(r['status']=='ready' for r in rows),'missing_or_invalid':sum(r['status']!='ready' for r in rows),'no_audio':len(skips),'unknown_audio':len(unknown),'unknown_audio_ids':unknown,'cache_bytes':sum(r.get('size_bytes',0) for r in rows),'rows':rows,'asr_requests':0}
    v.atomic_json(CACHE/'inventory.json',report)
    print(json.dumps({k:x for k,x in report.items() if k!='rows'},ensure_ascii=False),flush=True)
    return report

class Extractor:
    def __init__(self,report):
        self.report=report;self.root=Path(report['root']);st=self.root.stat();self.identity=(st.st_dev,st.st_ino)
        self.stop=threading.Event();self.lock=threading.Lock();self.owned={};self.done=0;self.failed=0;self.total=report['missing_or_invalid']
    def disk(self):
        try:
            s=self.root.stat()
            if (s.st_dev,s.st_ino)!=self.identity:raise OSError('硬盘身份改变')
        except OSError:self.stop.set();raise v.SourceIOPause('硬盘失联，暂停；不创建挂载目录') from None
    def cancel(self,*args):
        self.stop.set()
        with self.lock:
            for proc in list(self.owned.values()):v.stop_owned(proc)
    def progress(self,status='extracting'):
        v.atomic_json(CACHE/'progress.json',{'runner_pid':os.getpid(),'status':status,'ready_before':self.report['ready'],'extracted_now':self.done,'failed_now':self.failed,'remaining':max(0,self.total-self.done-self.failed),'owned_pids':list(self.owned),'network_requests':0,'whisper_runs':0,'updated_at':time.time()})
    def one(self,row):
        if (BASE/'pause.request').exists():self.stop.set();return
        if self.stop.is_set():return
        ident=row['id'];audio=CACHE/'audio'/f'{ident}.wav';temp=audio.with_suffix('.part.wav');log=CACHE/'logs'/f'{ident}.log'
        try:
            self.disk();path=source(self.root,row)
            cmd=[v.executable(None,'ffmpeg'),'-nostdin','-v','error','-y','-threads','1','-copyts','-start_at_zero','-i',str(path),'-map','0:a:0','-vn','-af','aresample=16000:async=1:first_pts=0','-ac','1','-c:a','pcm_s16le',str(temp)]
            with log.open('ab') as f:
                with self.lock:
                    if self.stop.is_set():return
                    proc=subprocess.Popen(cmd,stdout=f,stderr=f,**({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}));self.owned[proc.pid]=proc
                try:proc.wait(timeout=3600)
                finally:
                    if proc.poll() is None:v.stop_owned(proc)
                    with self.lock:self.owned.pop(proc.pid,None)
            if self.stop.is_set():return
            self.disk();source(self.root,row)
            if proc.returncode:
                if v.io_problem(log.read_text(errors='replace')):raise v.SourceIOPause('FFmpeg读取I/O异常')
                raise ValueError('提取失败，查看日志')
            info=wav_info(temp,row['expected_seconds']);digest=hashlib.sha256(temp.read_bytes()).hexdigest()
            if audio.exists():raise ValueError('已有独立音轨文件，拒绝覆盖')
            os.replace(temp,audio)
            v.atomic_json(CACHE/'manifests'/f'{ident}.json',{'source':row['source'],'relative_path':row['relative_path'],'audio_sha256':digest,'audio_path':str(audio),'conversion':'16kHz mono PCM full timeline','status':'ready',**info})
            with self.lock:self.done+=1;self.progress()
        except v.SourceIOPause:
            self.cancel()
        except (OSError,ValueError,subprocess.TimeoutExpired) as e:
            if v.io_problem(e,self.root):self.cancel()
            try:self.disk()
            except v.SourceIOPause:self.stop.set()
            with self.lock:self.failed+=1;self.progress()
            v.atomic_json(CACHE/'manifests'/f'{ident}.json',{'source':row['source'],'status':'failed','error':str(e)})
        finally:temp.unlink(missing_ok=True)
    def run(self,workers):
        for d in ['audio','manifests','logs']:(CACHE/d).mkdir(exist_ok=True)
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT,self.cancel);signal.signal(signal.SIGTERM,self.cancel)
        self.progress()
        pending=iter(r for r in self.report['rows'] if r['status']!='ready')
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            active=set()
            while not self.stop.is_set():
                if (BASE/'pause.request').exists():self.stop.set();break
                while len(active)<workers:
                    row=next(pending,None)
                    if row is None:break
                    active.add(pool.submit(self.one,row))
                if not active:break
                completed,active=concurrent.futures.wait(active,timeout=1,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in completed:future.result()
        self.progress('paused' if self.stop.is_set() else 'finished')
        print(json.dumps({'status':'paused' if self.stop.is_set() else 'finished','extracted':self.done,'failed':self.failed,'upload_requests':0}),flush=True)

