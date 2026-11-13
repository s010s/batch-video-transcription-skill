"""Safe offline single-sample HTML rendering, without IO side effects."""
import json
import html as html_module

def script_json(data):
    return json.dumps(data,ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')

def render(data):
    payload=script_json(data)
    html=r'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>视频转写核对</title><style>body{font:18px system-ui;margin:24px;max-width:1000px}video{width:100%;max-height:420px}button{display:block;width:100%;text-align:left;white-space:pre-wrap;margin:10px 0;padding:12px;border:1px solid #ddd;background:#fff;font:inherit;cursor:pointer}.active{background:#e6f4ef}summary{cursor:pointer}</style><h1>视频转写核对</h1><p>转写结果 · 待核时长 · 句数占位 → 段数占位 · 待听校，编号不代表身份。普通停顿合并；换人、未知、重叠或明确拼接边界拆段。点击文字跳转。</p><video id="video" controls preload="metadata"></video><h2>发言段采访稿</h2><div id="turns"></div><details><summary>展开全部10句及逐句时间码</summary><div id="sentences"></div></details><script>const data=PAYLOAD;const video=document.getElementById('video');video.src=data.video;const tracked=[];function add(parent,s,label){const b=document.createElement('button');b.textContent=`[${s.start.toFixed(2)}–${s.end.toFixed(2)}秒] ${label}`;b.onclick=()=>{video.currentTime=s.start;video.play().catch(()=>{});};document.getElementById(parent).append(b);tracked.push([b,s]);}data.turns.forEach(t=>{const speaker=data.segments[t.sentence_indices[0]].speaker_id;add('turns',t,`说话人 ${speaker??'未知'}\n${t.texts.join('\n')}`);});data.segments.forEach(s=>add('sentences',s,`说话人 ${s.speaker_id??'未知'}：${s.text}`));video.addEventListener('timeupdate',()=>tracked.forEach(([b,s])=>b.classList.toggle('active',video.currentTime>=s.start&&video.currentTime<s.end)));</script>'''.replace('PAYLOAD',payload)
    title=html_module.escape(data.get('title','视频转写核对'))
    html=html.replace('视频转写核对',title)
    html=html.replace('待核时长',f"{data.get('duration_seconds',0):.2f}秒").replace('句数占位',f"{len(data['segments'])}句").replace('段数占位',f"{len(data['turns'])}个发言段").replace('全部10句',f"全部{len(data['segments'])}句")
    return html
