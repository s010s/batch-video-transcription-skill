'use strict';
const staticData = window.VIDEO_LIBRARY;
const staticMode = location.protocol==='file:' || Boolean(staticData);
const token = new URLSearchParams(location.search).get('token');
const $ = id => document.getElementById(id);
const states = {pending:'待处理', extracting:'正在抽取音轨', transcribing:'正在转写', done:'已完成', failed:'失败', interrupted:'已中断 · 可续跑', no_audio:'无音轨', no_speech:'未识别到语音', no_words:'未识别出文字'};
let videos = [], selected = null, revision = '', seekRequest = null, currentFolder = '';
const openFolders = new Set();
const filePages=new Map(),folderLimits=new Map();let searchPage=0,transcriptPage=0,currentMatched=[];
const PAGE_SIZE=100,TRANSCRIPT_SIZE=200;
let mediaUnavailable=false;
let following=true, activeStart=null, mediaGeneration=0, expectedMedia='';
function followState(){ $('followstate').textContent=following?'正在跟随播放':'已暂停跟随 · 可自由阅读';$('follow').textContent=following?'跟随中':'恢复跟随播放';}
function pauseFollow(){following=false;followState();}
$('follow').onclick=()=>{following=true;followState();highlight(true);};
$('transcript').addEventListener('wheel',pauseFollow,{passive:true});
$('transcript').addEventListener('touchmove',pauseFollow,{passive:true});
$('transcript').addEventListener('pointerdown',e=>{if(e.target===$('transcript'))pauseFollow();});
$('transcript').addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(e.key))pauseFollow();});
const player = $('player');

const resizer=$('sidebar-resizer');let preferredWidth=300,currentWidth=300,dragging=null;
try{const saved=Number(localStorage.getItem('videolib.sidebar-width'));if(Number.isFinite(saved)&&saved>0)preferredWidth=saved;}catch(e){}
function sidebarBounds(){return {min:220,max:Math.max(220,Math.min(460,(window.innerWidth||1200)-650))};}
function sidebarWidth(value,persist=false){const b=sidebarBounds();currentWidth=Math.round(Math.max(b.min,Math.min(b.max,value)));document.documentElement.style.setProperty('--sidebar-width',currentWidth+'px');resizer.setAttribute('aria-valuenow',String(currentWidth));resizer.setAttribute('aria-valuemax',String(b.max));resizer.setAttribute('aria-valuetext',currentWidth+' 像素');if(persist){preferredWidth=currentWidth;try{localStorage.setItem('videolib.sidebar-width',String(currentWidth));}catch(e){}}}
function endResize(cancel=false){if(!dragging)return;const state=dragging;dragging=null;document.body.classList.remove('resizing-sidebar');try{if(resizer.hasPointerCapture(state.id))resizer.releasePointerCapture(state.id);}catch(e){}sidebarWidth(cancel?state.width:currentWidth,!cancel);}
resizer.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();dragging={id:e.pointerId,x:e.clientX,width:currentWidth};resizer.focus();document.body.classList.add('resizing-sidebar');try{resizer.setPointerCapture(e.pointerId);}catch(err){endResize(true);}});
resizer.addEventListener('pointermove',e=>{if(dragging&&e.pointerId===dragging.id){e.preventDefault();sidebarWidth(dragging.width+e.clientX-dragging.x);}});
resizer.addEventListener('pointerup',()=>endResize());resizer.addEventListener('pointercancel',()=>endResize(true));resizer.addEventListener('lostpointercapture',()=>endResize(true));
resizer.addEventListener('keydown',e=>{if(e.key==='Escape'){endResize(true);return;}const bounds=sidebarBounds();let value;if(e.key==='ArrowLeft')value=currentWidth-(e.shiftKey?32:16);else if(e.key==='ArrowRight')value=currentWidth+(e.shiftKey?32:16);else if(e.key==='Home')value=bounds.min;else if(e.key==='End')value=bounds.max;else return;e.preventDefault();sidebarWidth(value,true);});
window.addEventListener('resize',()=>sidebarWidth(preferredWidth));sidebarWidth(preferredWidth);

let transcriptMode='turns',speakerFilter='all';
function transcriptUnits(v){
  const sentences=v.segments||[];if(transcriptMode==='sentences')return sentences;
  let turns=v.turns;
  if(!turns){turns=[];sentences.forEach((s,i)=>{const known=Number.isInteger(s.speaker_id)&&s.speaker_id>=0;const speaker=known?(s.speaker||String(s.speaker_id)):null;const prev=turns[turns.length-1];const overlap=s.overlap||Boolean(prev&&s.start<prev.end);const boundary=s.splice_boundary||s.source_boundary||s.sample_boundary;if(prev&&speaker!==null&&prev.speaker===speaker&&!overlap&&!boundary&&!prev.uncertain){prev.end=s.end;prev.texts.push(s.text);prev.sentence_indices.push(i);}else turns.push({start:s.start,end:s.end,texts:[s.text],sentence_indices:[i],speaker,uncertain:!known||overlap||boundary});});}
  return turns.map(t=>({...t,text:t.texts.join(''),speaker_id:sentences[t.sentence_indices[0]]?.speaker_id}));
}
function speakerKey(s){return Number.isInteger(s.speaker_id)&&s.speaker_id>=0?String(s.speaker_id):'unknown';}
function filteredUnits(v){const q=$('transcriptfilter').value.trim().toLocaleLowerCase();return transcriptUnits(v).filter(s=>(speakerFilter==='all'||speakerKey(s)===speakerFilter)&&(!q||s.text.toLocaleLowerCase().includes(q)));}
function speakerOptions(v){const select=$('speakerfilter');select.replaceChildren();const values=[...new Set((v.segments||[]).map(speakerKey))].sort((a,b)=>a==='unknown'?1:b==='unknown'?-1:Number(a)-Number(b));const all=el('option','','全部讲话人');all.value='all';select.append(all);for(const value of values){const option=el('option','',value==='unknown'?'未识别讲话人':'讲话人 '+value);option.value=value;select.append(option);}if(speakerFilter!=='all'&&!values.includes(speakerFilter))speakerFilter='all';select.value=speakerFilter;select.disabled=!values.length;}
function updateCopyScope(){const v=videos.find(x=>x.id===selected);const filtered=speakerFilter!=='all'||Boolean($('transcriptfilter').value.trim());const count=v?filteredUnits(v).length:0;$('copy').textContent=filtered?'复制筛选结果（'+count+unitLabel()+'）':'复制全文';$('copy').title=filtered?'复制全部筛选命中，包含其他页；按当前显示模式':'复制当前视频完整文字；按当前显示模式';}
$('speakerfilter').addEventListener('change',()=>{speakerFilter=$('speakerfilter').value;transcriptPage=0;const v=videos.find(v=>v.id===selected);if(v)renderTranscript(v);});
function unitLabel(){return transcriptMode==='turns'?'段':'句';}
function displayTime(t){return tc(transcriptMode==='turns'?Math.floor((t||0)+0.5):t);}
function speakerLabel(s){return '讲话人 '+(Number.isInteger(s.speaker_id)&&s.speaker_id>=0?s.speaker_id:'未知');}
$('transcriptmode').value=transcriptMode;
$('transcriptmode').addEventListener('change',()=>{transcriptMode=$('transcriptmode').value==='sentences'?'sentences':'turns';transcriptPage=0;searchPage=0;activeStart=null;const v=videos.find(v=>v.id===selected);if(v)renderTranscript(v);search();});
function tc(t){const n=Math.floor(t||0);return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(x=>String(x).padStart(2,'0')).join(':');}
function el(tag, cls, text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;}
function setFolder(path){searchPage=0;currentFolder=path;$('foldercurrent').textContent='当前文件夹：'+(path||'全部素材');search();}

function marked(text,q){const span=el('span');const lower=text.toLocaleLowerCase();let position=0,hit;if(!q){span.textContent=text;return span;}while((hit=lower.indexOf(q,position))!==-1){span.append(document.createTextNode(text.slice(position,hit)),el('mark','',text.slice(hit,hit+q.length)));position=hit+q.length;}span.append(document.createTextNode(text.slice(position)));return span;}
async function copyText(text,button){
  let copied=false;try{if(navigator.clipboard){await navigator.clipboard.writeText(text);copied=true;}}catch(e){}
  if(!copied){const field=$('copytext');field.value=text;$('copyfallback').hidden=false;field.focus();field.select();try{copied=Boolean(document.execCommand('copy'));}catch(e){}}
  if(copied){$('copyfallback').hidden=true;button.textContent='已复制';setTimeout(()=>{if(button===$('copy'))updateCopyScope();else button.textContent='复制';},1500);}else button.textContent='请手动复制';
}
$('copyselect').onclick=()=>{$('copytext').focus();$('copytext').select();};
$('copy').onclick=()=>{const v=videos.find(v=>v.id===selected);if(!v)return;const timed=$('copyformat').value==='timed';const text=filteredUnits(v).map(s=>timed?'['+displayTime(s.start)+' → '+displayTime(s.end)+'] '+(transcriptMode==='turns'?speakerLabel(s)+' ':'')+s.text:s.text).join('\n');copyText(text,$('copy'));};
$('transcriptfilter').addEventListener('input',()=>{transcriptPage=0;const v=videos.find(v=>v.id===selected);if(v)renderTranscript(v);});
$('transcriptclear').onclick=()=>{transcriptPage=0;$('transcriptfilter').value='';speakerFilter='all';const v=videos.find(v=>v.id===selected);if(v)renderTranscript(v);};
function renderFiles(){
  const filter=$('filter').value.toLocaleLowerCase();$('files').replaceChildren();
  const list=videos.filter(v=>v.relative_path.toLocaleLowerCase().includes(filter));
  const tree={folders:new Map(),files:[]};
  for(const v of list){const parts=v.relative_path.split('/');parts.pop();let node=tree;for(const part of parts){if(!node.folders.has(part))node.folders.set(part,{folders:new Map(),files:[]});node=node.folders.get(part);}node.files.push(v);}
  function append(node,parent,path){
    if(!filePages.has(path)){const selectedIndex=node.files.findIndex(v=>v.id===selected);filePages.set(path,Math.max(0,Math.floor(selectedIndex/PAGE_SIZE)));}
    const page=Math.min(filePages.get(path),Math.max(0,Math.ceil(node.files.length/PAGE_SIZE)-1));
    for(const v of node.files.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)){const b=el('button','file'+(v.id===selected?' selected':''));b.append(el('strong','',v.relative_path.split('/').pop()),el('small','',states[v.status]||v.status));b.title=v.relative_path;b.onclick=()=>select(v.id);parent.append(b);}
    if(node.files.length>PAGE_SIZE){const controls=el('div','paging');for(const [label,delta] of [['上一组',-1],['下一组',1]]){const button=el('button','',label);button.disabled=page+delta<0||(page+delta)*PAGE_SIZE>=node.files.length;button.onclick=()=>{filePages.set(path,page+delta);renderFiles();};controls.append(button);}controls.append(el('small','',(page+1)+' / '+Math.ceil(node.files.length/PAGE_SIZE)));parent.append(controls);}
    const folders=[...node.folders],limit=folderLimits.get(path)||100;
    for(const [name,child] of folders.slice(0,limit)){const full=path?path+'/'+name:name;const details=el('details','folder');details.append(el('summary','',name));details.open=openFolders.has(full)||videos.some(v=>v.id===selected&&v.relative_path.startsWith(full+'/'));const pick=el('button','folderpick','搜索此文件夹');pick.onclick=()=>{setFolder(full);$('scope').value='current';searchPage=0;search();};details.append(pick);const content=el('div','foldercontent');let mounted=false;function mount(){if(!mounted){append(child,content,full);mounted=true;}}if(details.open)mount();details.addEventListener('toggle',()=>{if(details.open){openFolders.add(full);mount();}else openFolders.delete(full);});details.append(content);parent.append(details);}
    if(folders.length>limit){const more=el('button','more','显示更多文件夹（每次100个）');more.onclick=()=>{folderLimits.set(path,limit+100);renderFiles();};parent.append(more);}
  }
  append(tree,$('files'),'');
  if(!list.length)$('files').append(el('p','empty',videos.length?'没有匹配的文件':'暂无素材，请联系提供方。'));
}

function renderSummary(v){const card=$('summarycard');card.replaceChildren(el('summary','','AI 摘要 · 须人工复核'));const summary=v.summary||{status:'not_generated'};if(summary.status!=='ready'){card.append(el('p','',summary.status==='stale'?'逐字稿已变化，摘要已过期。':!v.segments?.length?'没有可用逐字稿，未生成摘要。':'尚未生成摘要；逐字稿与搜索可正常使用。'));return;}card.append(el('p','',summary.overview));for(const topic of summary.topics||[])card.append(el('p','',topic.text));for(const q of summary.quotes||[]){const b=el('button','summaryquote',tc(q.start)+' '+q.text);b.onclick=()=>jump(q.start);card.append(b);}if(summary.limitations?.length)card.append(el('p','summary-limit','限制：'+summary.limitations.join('；')));}

function renderWordLink(v){const link=$('wordlink');link.hidden=true;link.removeAttribute('href');if(typeof v.word!=='string'||/^(?:[a-z][a-z0-9+.-]*:|[\/\\])/i.test(v.word))return;try{const url=new URL(v.word,location.href),page=new URL(location.href);if(url.protocol!==page.protocol||url.origin!==page.origin||url.search||url.hash||!url.pathname.toLowerCase().endsWith('.docx'))return;link.href=v.word;link.hidden=false;}catch(e){}}
function renderTranscript(v){
  renderWordLink(v);
  $('title').textContent=v.relative_path;$('state').textContent=states[v.status]||v.status;$('testbanner').hidden=!v.test_data;
  $('transcript').replaceChildren();
  renderSummary(v);speakerOptions(v);updateCopyScope();
  const filter=$('transcriptfilter').value.trim().toLocaleLowerCase();const all=transcriptUnits(v),matched=filteredUnits(v);
  currentMatched=matched;transcriptPage=Math.min(transcriptPage,Math.max(0,Math.ceil(matched.length/TRANSCRIPT_SIZE)-1));$('transcriptpaging').hidden=matched.length<=TRANSCRIPT_SIZE;$('transcriptpage').textContent=(transcriptPage+1)+' / '+Math.max(1,Math.ceil(matched.length/TRANSCRIPT_SIZE));$('transcriptprev').disabled=transcriptPage===0;$('transcriptnext').disabled=(transcriptPage+1)*TRANSCRIPT_SIZE>=matched.length;
  $('transcriptcount').textContent=(filter||speakerFilter!=='all')?'命中 '+matched.length+' / '+all.length+' '+unitLabel():'共 '+all.length+' '+unitLabel();
  for(const s of matched.slice(transcriptPage*TRANSCRIPT_SIZE,(transcriptPage+1)*TRANSCRIPT_SIZE)){const row=el('div','segment');row.dataset.start=s.start;row.dataset.end=s.end;const b=el('button','segment-jump');b.append(el('time','',(transcriptMode==='turns'?speakerLabel(s)+' · ':'')+displayTime(s.start)+' → '+displayTime(s.end)),marked(s.text,filter));b.onclick=()=>jump(s.start);const copy=el('button','segment-copy','复制');copy.setAttribute('aria-label','复制此段原话');copy.onclick=()=>copyText(s.text,copy);row.append(b,copy);$('transcript').append(row);}
  if((filter||speakerFilter!=='all')&&!matched.length)$('transcript').append(el('p','empty','当前讲话人和关键词筛选没有匹配文字；清除筛选可恢复全文。'));
  if(!(v.segments||[]).length){const msg=v.status==='no_audio'?'视频没有音轨。':v.status==='no_words'?'阿里服务未识别出文字或有效片段；不等同于原音频完全无人声。':v.status==='no_speech'?'音轨已处理，未识别到语音。':v.status==='failed'?'处理失败：'+(v.error||'请查看本地日志'):v.status==='interrupted'?'任务未完成，请联系提供方重新处理。':'此视频尚未生成文字稿，请联系提供方。';$('transcript').append(el('p','empty',msg));}
  highlight();
}
function select(id, at){
  const v=videos.find(x=>x.id===id);if(!v)return;const changed=id!==selected;
  selected=id;activeStart=null;if(changed){speakerFilter='all';transcriptPage=0;filePages.delete(v.relative_path.includes('/')?v.relative_path.slice(0,v.relative_path.lastIndexOf('/')):'');}renderFiles();
  if(changed){mediaGeneration++;mediaUnavailable=false;player.hidden=false;$('mediaerror').hidden=true;seekRequest=at===undefined?null:{at,id,generation:mediaGeneration};player.pause();expectedMedia=new URL(staticMode?v.media:'/media/'+id+'?token='+encodeURIComponent(token),location.href).href;player.src=expectedMedia;player.load();}
  else if(at!==undefined)jump(at);
  renderTranscript(v);
}
function jump(at){
  if(mediaUnavailable){seekRequest=null;$('mediaerror').hidden=false;$('mediaerror').textContent='需要原视频才能跳转播放；未附带原视频，可正常阅读和搜索文字稿。';return;}
  following=true;followState();
  if(player.readyState>=1){seekRequest=null;player.currentTime=Math.min(at,Number.isFinite(player.duration)?player.duration:at);highlight(true);player.play().catch(()=>{});}
  else seekRequest={at,id:selected,generation:mediaGeneration};
}
player.addEventListener('loadedmetadata',()=>{if(player.currentSrc!==expectedMedia||player.readyState<1)return;mediaUnavailable=false;player.hidden=false;$('mediaerror').hidden=true;const request=seekRequest;if(request&&request.id===selected&&request.generation===mediaGeneration){seekRequest=null;jump(request.at);}});
player.addEventListener('error',()=>{if(player.currentSrc&&player.currentSrc!==expectedMedia)return;seekRequest=null;mediaUnavailable=true;player.pause();player.hidden=true;$('mediaerror').textContent='未附带原视频，可正常阅读和搜索文字稿。若已附带视频，请检查浏览器是否支持其编码。';$('mediaerror').hidden=false;});
function highlight(force=false){
  const index=currentMatched.findIndex(s=>player.currentTime>=s.start&&player.currentTime<s.end);if(following&&player.readyState>=1&&player.currentSrc===expectedMedia&&index>=0&&Math.floor(index/TRANSCRIPT_SIZE)!==transcriptPage){transcriptPage=Math.floor(index/TRANSCRIPT_SIZE);const v=videos.find(v=>v.id===selected);if(v){renderTranscript(v);return;}}
  let active=null;for(const row of $('transcript').querySelectorAll('.segment')){const isActive=player.currentTime>=Number(row.dataset.start)&&player.currentTime<Number(row.dataset.end);row.classList.toggle('active',isActive);if(isActive&&!active)active=row;}
  if(active&&following&&(force||activeStart!==active.dataset.start)){const box=$('transcript');box.scrollTo({top:box.scrollTop+active.getBoundingClientRect().top-box.getBoundingClientRect().top-40,behavior:'smooth'});}
  activeStart=active?active.dataset.start:null;const filter=$('transcriptfilter').value.trim();if(filter||speakerFilter!=='all'){const v=videos.find(v=>v.id===selected),all=v?transcriptUnits(v):[];const count=currentMatched.length;const hidden=!active&&all.some(s=>player.currentTime>=s.start&&player.currentTime<s.end);$('transcriptcount').textContent='命中 '+count+' / '+all.length+' '+unitLabel()+(hidden?' · 当前播放'+unitLabel()+'被筛选隐藏，清除可查看':'');}
}
player.addEventListener('timeupdate',()=>highlight());
player.addEventListener('seeking',()=>highlight(true));
player.addEventListener('seeked',()=>highlight(true));
function search(){
  $('searchpaging').hidden=true;
  const q=$('search').value.trim().toLocaleLowerCase(), filter=$('filter').value.toLocaleLowerCase();$('results').replaceChildren();if(!q){$('searchcount').textContent='';return;}
  const scope=$('scope').value==='current'?currentFolder:'';
  let count=0;for(const v of videos){if(!v.relative_path.toLocaleLowerCase().includes(filter)||(scope&&!v.relative_path.startsWith(scope+'/')))continue;const segments=transcriptUnits(v);for(let i=0;i<segments.length;i++){const s=segments[i];if(!s.text.toLocaleLowerCase().includes(q))continue;count++;if(count<=searchPage*PAGE_SIZE||count>(searchPage+1)*PAGE_SIZE)continue;const b=el('button','hit');b.append(el('strong','',v.relative_path.split('/').pop()+' · '+tc(s.start)),el('small','',v.relative_path.includes('/')?'文件夹：'+v.relative_path.slice(0,v.relative_path.lastIndexOf('/')):'素材根目录'),marked(s.text,q));const context=[segments[i-1]?.text,segments[i+1]?.text].filter(Boolean).map(t=>t.slice(0,160)).join(' / ');if(context){const ctx=el('small','context');ctx.append(document.createTextNode('上下文：'),marked(context,q));b.append(ctx);}b.onclick=()=>select(v.id,s.start);$('results').append(b);}}
  $('searchpaging').hidden=count<=PAGE_SIZE;$('searchpage').textContent=(searchPage+1)+' / '+Math.max(1,Math.ceil(count/PAGE_SIZE));$('searchprev').disabled=searchPage===0;$('searchnext').disabled=(searchPage+1)*PAGE_SIZE>=count;
  $('searchcount').textContent=(scope?'当前文件夹 '+scope+' · ':'全部素材 · ')+(count?'共 '+count+' 处命中'+(count>PAGE_SIZE?' · 每页100处':'')+' · 点击跳转':'没有找到匹配文字');
}
$('folderall').onclick=()=>{setFolder('');$('scope').value='all';search();};
$('scope').addEventListener('change',()=>{searchPage=0;search();});
$('searchprev').onclick=()=>{searchPage--;search();};$('searchnext').onclick=()=>{searchPage++;search();};
$('transcriptprev').onclick=()=>{pauseFollow();transcriptPage--;const v=videos.find(v=>v.id===selected);if(v)renderTranscript(v);};$('transcriptnext').onclick=()=>{pauseFollow();transcriptPage++;const v=videos.find(v=>v.id===selected);if(v)renderTranscript(v);};
let searchTimer=null;function queueSearch(){searchPage=0;clearTimeout(searchTimer);searchTimer=setTimeout(search,150);}
$('filter').addEventListener('input',()=>{filePages.clear();renderFiles();queueSearch();});$('search').addEventListener('input',queueSearch);
async function refresh(){try{let data=staticData;if(staticMode&&!data)throw Error('missing data.js');if(!data){const r=await fetch('/api/library?token='+encodeURIComponent(token),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);data=await r.json();}const newRevision=JSON.stringify(data);if(newRevision===revision)return;revision=newRevision;videos=data.videos;$('root').textContent=data.root_name;const completed=videos.filter(v=>['done','no_audio','no_speech','no_words'].includes(v.status)).length,failed=videos.filter(v=>v.status==='failed').length,busy=videos.filter(v=>['extracting','transcribing'].includes(v.status)).length;$('summary').textContent=data.provider==='aliyun-fun-asr'?videos.length+' 条视频 · '+videos.filter(v=>v.status==='done').length+' 有文字 · '+videos.filter(v=>v.status==='no_words').length+' 未识别出文字 · '+videos.filter(v=>v.status==='no_audio').length+' 无音轨':videos.length+' 条视频 · '+completed+' 已处理 · '+failed+' 失败'+(busy?' · '+busy+' 处理中':'')+(data.scan_errors?' · 扫描警告 '+data.scan_errors:'');renderFiles();search();if(selected&&videos.some(v=>v.id===selected))renderTranscript(videos.find(v=>v.id===selected));else if(videos.length)select((videos.find(v=>v.status==='done')||videos[0]).id);else{selected=null;player.removeAttribute('src');player.load();$('title').textContent='选择一条素材';renderWordLink({});$('state').textContent='';$('testbanner').hidden=true;$('transcript').replaceChildren(el('p','empty','此文字库暂无素材，请联系提供方。'));}}catch(e){$('summary').textContent=staticMode?'文字稿数据加载失败，请联系提供方。':'连接中断，请确认本地服务仍在运行。';}}
refresh();if(!staticMode)setInterval(refresh,3000);
