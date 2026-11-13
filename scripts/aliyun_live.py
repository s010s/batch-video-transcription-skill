"""Explicit single-sample flow. Credentials/policies/signed URLs are never persisted."""
import http.client
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import aliyun_sample as a
import videolib as v


def oss_endpoint(url):
    try:u=urllib.parse.urlsplit(url);port=u.port
    except ValueError:raise ValueError('OSS地址格式错误') from None
    if u.scheme!='https' or u.username or u.password or port not in (None,443) or not re.fullmatch(r'[a-z0-9.-]+\.oss-cn-beijing\.aliyuncs\.com',u.hostname or ''):
        raise ValueError('只允许官方北京OSS HTTPS地址')
    return url


def _safe_open_once(request,limit):
    try:
        with urllib.request.build_opener(a.NoRedirect()).open(request,timeout=90) as response:
            data=response.read(limit+1)
            if len(data)>limit:raise ValueError('响应超过小样大小上限')
            return data
    except urllib.error.HTTPError as e:raise a.ProviderError(e.code) from None
    except (urllib.error.URLError,TimeoutError,ConnectionError,http.client.HTTPException) as exc:raise a.NetworkFailure(request.get_method(),type(getattr(exc,'reason',exc)).__name__) from None


def safe_open(request,*args,**kwargs):
    # GET can repeat; OSS upload POST is retried only as a fresh object by upload().
    for attempt in range(3):
        try:return _safe_open_once(request,*args,**kwargs)
        except (a.NetworkFailure,a.ProviderError) as exc:
            retryable=isinstance(exc,a.NetworkFailure) or exc.status in (429,500,502,503,504)
            if request.get_method()!='GET' or not retryable or attempt==2:raise
            a.time.sleep(2**attempt)

def upload(api,path):
    policy=api.request_json('/api/v1/uploads?action=getPolicy&model=fun-asr').get('data',{})
    try:
        if policy.get('x_oss_object_acl')!='private':raise ValueError('拒绝非private上传策略')
        host=oss_endpoint(policy['upload_host']);directory=policy['upload_dir']
        if not isinstance(directory,str) or not re.fullmatch(r'[A-Za-z0-9_/-]+',directory) or '..' in directory.split('/'):
            raise ValueError('上传目录异常')
        name='sample-'+uuid.uuid4().hex+'.wav';key=directory.rstrip('/')+'/'+name
        fields={'OSSAccessKeyId':policy['oss_access_key_id'],'Signature':policy['signature'],'policy':policy['policy'],
                'x-oss-object-acl':policy['x_oss_object_acl'],'x-oss-forbid-overwrite':policy['x_oss_forbid_overwrite'],
                'key':key,'success_action_status':'200'}
        boundary='----videolib'+uuid.uuid4().hex;parts=[]
        for field,value in fields.items():
            if not isinstance(value,str):raise ValueError('上传策略字段异常')
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
        if path.stat().st_size>1_000_000_000:raise ValueError('音频超过官方临时上传1GB上限')
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
        prefix=b''.join(parts);suffix=f'\r\n--{boundary}--\r\n'.encode()
        def stream():
            yield prefix
            with path.open('rb') as f:
                while chunk:=f.read(1048576):yield chunk
            yield suffix
        # Stream bounded chunks; no Bearer or policy logging.
        safe_open(urllib.request.Request(host,data=stream(),headers={'Content-Type':'multipart/form-data; boundary='+boundary,'Content-Length':str(len(prefix)+path.stat().st_size+len(suffix))},method='POST'),1_000_000)
        return 'oss://'+key
    except KeyError:raise ValueError('官方上传策略缺少必需字段') from None
    finally:policy=None


def safe_result(raw):
    """Drop transport/auth metadata before saving, without rewriting transcript text."""
    blocked={'authorization','api_key','apikey','access_token','refresh_token','signature','policy','file_url','transcription_url','oss_url','upload_url','oss_access_key_id'}
    if isinstance(raw,dict):return {k:('[transport metadata omitted]' if k.lower() in blocked else safe_result(value)) for k,value in raw.items()}
    if isinstance(raw,list):return [safe_result(value) for value in raw]
    return raw

def export(raw,sample,destination):
    raw=safe_result(raw);doc=a.normalize_result(raw,sample);turns=a.merge_turns(doc['segments'])
    v.atomic_json(destination/'raw-response.json',raw);v.atomic_json(destination/'normalized.json',doc);v.atomic_json(destination/'turns.json',turns)
    (destination/'逐句稿.txt').write_text('\n'.join(s['text'] for s in doc['segments'])+'\n',encoding='utf-8')
    (destination/'时间码.txt').write_text('\n'.join(f"[{v.timecode(s['start'],'.')} → {v.timecode(s['end'],'.')}] {s['speaker'] or '未知说话人'} {s['text']}" for s in doc['segments'])+'\n',encoding='utf-8')
    (destination/'字幕.srt').write_text('\n\n'.join(f"{n}\n{v.timecode(s['start'])} --> {v.timecode(s['end'])}\n{s['text']}" for n,s in enumerate(doc['segments'],1))+'\n',encoding='utf-8')
    (destination/'发言段采访稿.txt').write_text('【云端转写 · 待听校 · 说话人编号仅本片有效】\n'+'\n\n'.join(f"[{v.timecode(t['start'],'.')} → {v.timecode(t['end'],'.')}] {t['speaker'] or '未知说话人'}\n"+'\n'.join(t['texts']) for t in turns)+'\n',encoding='utf-8')
    return doc


