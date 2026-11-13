import http.client
#!/usr/bin/env python3
"""Session-only credential entry and bounded Fun-ASR sample contracts. Explicit bounded audio upload via aliyun_live."""
import argparse
import getpass
import json
import math
from pathlib import Path
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import warnings
import wave
import videolib as v

BASE=Path(__file__).resolve().parent
DEFAULT_ORIGIN='https://dashscope.aliyuncs.com'
DOC='https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-http-api'


def api_origin(base_url):
    try:
        u=urllib.parse.urlsplit(base_url.strip());port=u.port
    except ValueError:
        raise ValueError('Base URL 格式错误') from None
    if u.scheme!='https' or u.username or u.password or u.query or u.fragment or port not in (None,443):
        raise ValueError('Base URL 必须为无凭据/查询参数的官方北京 HTTPS 地址')
    if u.hostname!='dashscope.aliyuncs.com' and not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}\.cn-beijing\.maas\.aliyuncs\.com',u.hostname or ''):
        raise ValueError('仅支持官方北京域名dashscope.aliyuncs.com或实际业务空间域名')
    if u.path.rstrip('/') not in ('','/api/v1','/compatible-mode/v1'):
        raise ValueError('Base URL 路径不属于已核实的入口')
    return 'https://'+u.hostname


class SessionCredential:
    __slots__=('_secret',)
    def __init__(self,secret):
        if not isinstance(secret,str):
            raise ValueError('Key 必须为字符串；不回显输入')
        secret=secret.strip()
        if not secret.startswith('sk'):
            raise ValueError('Key 必须以小写 sk 开头；不回显输入')
        if any(unicodedata.category(char) in ('Cc','Zl','Zp') for char in secret):
            raise ValueError('Key 内部含换行或控制字符，不能用于 HTTP 请求头；不回显输入')
        self._secret=secret
    def __repr__(self):return '<SessionCredential hidden>'
    def header(self):
        if self._secret is None:raise ValueError('凭证会话已结束')
        return 'Bearer '+self._secret
    def close(self):self._secret=None
    @classmethod
    def prompt(cls):
        if not sys.stdin.isatty():
            raise ValueError('必须由用户自己的交互终端隐藏输入；拒绝管道、文件或助手代填')
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            try:secret=getpass.getpass('API Key（隐藏输入，不保存）：')
            except getpass.GetPassWarning:
                raise ValueError('终端不能保证隐藏输入，已停止；不会降级为可见输入') from None
        try:return cls(secret)
        finally:secret=None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


class ProviderError(ValueError):
    def __init__(self,status,code='',message='',request_id=''):
        self.status=status;self.code=code;self.message=message;self.request_id=request_id
        super().__init__(f'官方服务 HTTP {status}；错误代码 {code or "unknown"}；不回显响应或凭据')


class NetworkFailure(ValueError):
    def __init__(self,method,kind):
        self.method=method;self.kind=kind
        super().__init__('官方服务网络请求失败；凭据未回显；POST不自动重投')

class WorkspaceAPI:
    """Bearer can only go to the exact user-selected official Beijing workspace host."""
    def __init__(self,origin,credential):
        self.origin=api_origin(origin);self.credential=credential
        self.opener=urllib.request.build_opener(NoRedirect())
    def request_json(self,path,method='GET',body=None,extra_headers=None):
        for attempt in range(3):
            try:return self._request_json_once(path,method,body,extra_headers)
            except (NetworkFailure,ProviderError) as exc:
                retryable=isinstance(exc,NetworkFailure) or exc.status in (429,500,502,503,504)
                if method!='GET' or not retryable or attempt==2:raise
                time.sleep(2**attempt)
    def _request_json_once(self,path,method='GET',body=None,extra_headers=None):
        if not path.startswith('/api/v1/') or '://' in path or '\r' in path or '\n' in path:
            raise ValueError('只接受固定原生 API 路径')
        headers={'Authorization':self.credential.header()}
        if any(k.lower()=='authorization' for k in (extra_headers or {})):raise ValueError('禁止覆盖认证头')
        headers.update(extra_headers or {})
        data=None
        if body is not None:data=json.dumps(body).encode();headers['Content-Type']='application/json'
        request=urllib.request.Request(self.origin+path,data=data,headers=headers,method=method)
        try:
            with self.opener.open(request,timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            # Never print request headers, server body, or token-bearing redirect URLs.
            code='';message='';request_id=''
            try:
                error_payload=json.loads(error.read(65536))
                message=error_payload.get('message','');request_id=error_payload.get('request_id','')
                candidate=error_payload.get('code','')
                if isinstance(candidate,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',candidate):code=candidate
            except (ValueError,TypeError):pass
            raise ProviderError(error.code,code,message,request_id) from None
        except (urllib.error.URLError,TimeoutError,ConnectionError,http.client.HTTPException) as exc:
            raise NetworkFailure(method,type(getattr(exc,'reason',exc)).__name__) from None
    def check_auth(self):return self.request_json('/api/v1/models?model=fun-asr')
    @staticmethod
    def submit_contract(temporary_oss_url):
        if not temporary_oss_url.startswith('oss://'):
            raise ValueError('小样只允许官方临时上传结果，不建立公开存储桶')
        return {'model':'fun-asr','input':{'file_urls':[temporary_oss_url]},
                'parameters':{'channel_id':[0],'diarization_enabled':True,'language_hints':['zh']}}
    def submit(self,temporary_oss_url,official_upload_verified=False):
        if not official_upload_verified:raise ValueError('上传适配器尚未完成实际响应核实，禁止提交真实任务')
        return self.request_json('/api/v1/services/audio/asr/transcription','POST',self.submit_contract(temporary_oss_url),
                                 {'X-DashScope-Async':'enable','X-DashScope-OssResourceResolve':'enable'})
    def task(self,task_id):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,100}',task_id):raise ValueError('非法 task_id')
        return self.request_json('/api/v1/tasks/'+task_id)


def audio_seconds(path):
    with wave.open(str(path)) as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2:
            raise ValueError('说话人分离小样必须使用单声道PCM WAV')
        return wav.getnframes()/wav.getframerate()


def normalize_result(raw,sample):
    segments=[]
    for transcript in raw.get('transcripts',[]):
        for sentence in transcript.get('sentences',[]):
            begin,end=sentence.get('begin_time'),sentence.get('end_time')
            if type(begin) is not int or type(end) is not int or begin<0 or end<begin:
                raise ValueError('服务时间码必须为有效毫秒')
            if end>sample['duration_seconds']*1000+1000:raise ValueError('服务时间码超出样本长度，需核对')
            raw_speaker=sentence.get('speaker_id')
            speaker=raw_speaker if type(raw_speaker) is int and raw_speaker>=0 else None
            segments.append({'start':sample['offset_seconds']+begin/1000,'end':sample['offset_seconds']+end/1000,
                             'text':sentence['text'],'speaker_id':speaker,'speaker_scope':sample['sample_id'],
                             'speaker':None if speaker is None else sample['sample_id']+':speaker:'+str(speaker),
                             'raw_speaker_id':raw_speaker,'source_begin_ms':begin,'source_end_ms':end,'words_ms':sentence.get('words',[]),'source_sentence_id':sentence.get('sentence_id'),'overlap':bool(sentence.get('overlap',False))})
    return {'schema':1,'id':v.key(sample['sample_id']+'\0'+sample['source_relative_path']),'relative_path':sample['source_relative_path'],'sample_id':sample['sample_id'],
            'time_unit':'seconds','timeline':'original video start','clip_offset_seconds':sample['offset_seconds'],
            'speaker_ids_are_clip_scoped':True,'segments':segments,'provider':'aliyun-fun-asr','review_status':'needs_listening_review'}


def merge_turns(segments,max_gap_seconds=None):
    """Merge consecutive known speakers across pauses; explicit boundaries stay split."""
    turns=[]
    for n,s in enumerate(segments):
        uncertain=[]
        if s['speaker'] is None:uncertain.append('unknown_speaker')
        overlap=s.get('overlap',False) or bool(turns and s['start']<turns[-1]['end'])
        if overlap:uncertain.append('overlap_or_time_order')
        gap=s['start']-turns[-1]['end'] if turns else 0
        if any(s.get(flag,False) for flag in ('splice_boundary','source_boundary','sample_boundary')):uncertain.append('source_boundary')
        if turns and max_gap_seconds is not None and gap>max_gap_seconds:uncertain.append('time_gap')
        if turns and s['speaker'] is not None and not uncertain and not turns[-1]['review_notes'] and turns[-1]['speaker']==s['speaker']:
            turns[-1]['end']=s['end'];turns[-1]['texts'].append(s['text']);turns[-1]['sentence_indices'].append(n)
        else:turns.append({'start':s['start'],'end':s['end'],'speaker':s['speaker'],'texts':[s['text']],'sentence_indices':[n],'review_notes':uncertain})
    return turns


