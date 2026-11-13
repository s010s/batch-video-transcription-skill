"""Create a new, versioned Word summary from the batch's verified local results."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from docx import Document
from docx.shared import Cm, Pt
import batch_paths as paths
from export_interview_docx import timestamp


def _json(path):
    if path.is_symlink():
        raise ValueError('Result file must not be a symbolic link')
    return json.loads(path.read_text(encoding='utf-8'))


def build(store):
    """Caller must hold the batch operation lock. No network or manifest mutation."""
    store.disk()
    if store.recovery_required or (store.path.parent/'.pending-state.json').exists():
        raise ValueError('Receipt recovery required before merging')
    data=store.data
    paths.validate_export(data)
    root=Path(data['root']).resolve(strict=True)
    st=root.stat()
    if [st.st_dev,st.st_ino]!=data['root_identity']:
        raise ValueError('Source directory identity changed')
    out=Path(data['output_root']).resolve(strict=True)
    document=Document();section=document.sections[0]
    section.page_width=Cm(21);section.page_height=Cm(29.7)
    section.top_margin=section.bottom_margin=Cm(2.2)
    section.left_margin=section.right_margin=Cm(2.3)
    normal=document.styles['Normal'];normal.font.size=Pt(11)
    normal.paragraph_format.line_spacing=1.35
    document.core_properties.author='';document.core_properties.last_modified_by=''
    document.core_properties.title='Video Transcription Summary'
    document.add_heading('视频转写汇总',0)
    jobs=sorted(data['jobs'].values(),key=lambda j:j['relative_path'])
    done=[j for j in jobs if j['status']=='exported']
    pending=[j for j in jobs if j['status']!='exported']
    document.add_paragraph(f'共 {len(jobs)} 个来源，已导出 {len(done)} 个。')
    if pending:
        document.add_paragraph('尚未完成的来源：')
        for job in pending:
            document.add_paragraph(f"{job['relative_path']} — {job['status']}")
    expected=[];receipts=[];seen=set()
    work=store.path.parent.parent.resolve(strict=True)
    for job in done:
        rel=PurePosixPath(job['relative_path'])
        if rel.is_absolute() or '..' in rel.parts or rel.as_posix() in seen:
            raise ValueError('Invalid or duplicate source path')
        seen.add(rel.as_posix())
        source=root/Path(rel.as_posix())
        if not source.resolve(strict=True).is_relative_to(root):raise ValueError('Source outside media directory')
        stat=source.stat()
        if stat.st_size!=job['source']['size'] or stat.st_mtime_ns!=job['source']['mtime_ns']:
            raise ValueError('Source fingerprint changed')
        result=Path(job['result_dir'])
        resolved=result.resolve(strict=True)
        if result.is_symlink() or not (resolved.is_relative_to(work) or resolved.is_relative_to(out)):
            raise ValueError('Result outside batch directories')
        normalized=_json(result/'normalized.json');turns=_json(result/'turns.json')
        normalized_hash=hashlib.sha256((result/'normalized.json').read_bytes()).hexdigest()
        turns_hash=hashlib.sha256((result/'turns.json').read_bytes()).hexdigest()
        version=hashlib.sha256(json.dumps({'exporter':'word-html-v2','source':job['source'],
            'audio_sha256':job.get('audio_sha256'),'normalized_sha256':normalized_hash,
            'turns_sha256':turns_hash},sort_keys=True).encode()).hexdigest()
        receipt=job.get('export_receipt',{})
        if receipt.get('version')!=version:
            raise ValueError('Export receipt version mismatch; preserve changed results for review')
        word_rel=PurePosixPath(receipt.get('word_relative_path',''))
        if word_rel.is_absolute() or '..' in word_rel.parts or not word_rel.parts:
            raise ValueError('Invalid exported document path')
        word=out/Path(word_rel.as_posix())
        if word.is_symlink() or not word.resolve(strict=True).is_relative_to(out):
            raise ValueError('Exported document outside output directory')
        if hashlib.sha256(word.read_bytes()).hexdigest()!=receipt.get('word_sha256'):
            raise ValueError('Exported document hash mismatch; preserve edited document')
        segments=normalized['segments']
        if normalized['relative_path']!=rel.as_posix():raise ValueError('Result source mismatch')
        if [text for turn in turns for text in turn['texts']] != [s['text'] for s in segments]:
            raise ValueError('Turn text mismatch')
        if [i for turn in turns for i in turn['sentence_indices']] != list(range(len(segments))):
            raise ValueError('Turn sentence indices mismatch')
        if not segments and normalized.get('recognition_outcome')!='no_recognized_words':
            raise ValueError('Empty result lacks explicit provider outcome')
        document.add_heading(rel.as_posix(),1)
        if not segments:
            text='本段服务未识别出文字。此说明不是对白转写，也不表示已确认视频中无人说话。'
            document.add_paragraph(text);expected.append(text)
        previous=0.0
        for turn in turns:
            start=float(turn['start']);end=float(turn['end'])
            if start<previous or start<0 or end<start or end>float(job['duration_seconds'])+0.01:
                raise ValueError('Invalid transcript timestamp')
            previous=start
            idx=turn['sentence_indices'][0];speaker=segments[idx].get('speaker_id')
            label='未知' if speaker is None else str(speaker)
            document.add_heading(f'讲话人 {label}    {timestamp(start)}–{timestamp(end)}',2)
            text=''.join(turn['texts']);document.add_paragraph(text);expected.append(text)
        receipts.append({'source':rel.as_posix(),'task_id':job.get('task_id'),'audio_sha256':job.get('audio_sha256'),
                         'result_sha256':hashlib.sha256((result/'normalized.json').read_bytes()).hexdigest(),
                         'turns_sha256':hashlib.sha256((result/'turns.json').read_bytes()).hexdigest()})
    # Exclusive creation prevents an existing summary, including a user-edited one, from being overwritten.
    target=None
    for n in range(1,10001):
        candidate=out/('Transcript-Summary'+('' if n==1 else f'-{n}')+'.docx')
        try:
            with candidate.open('xb') as handle:document.save(handle)
            target=candidate;break
        except FileExistsError:continue
    if target is None:raise ValueError('No free summary filename')
    reopened=Document(target);body=[p.text for p in reopened.paragraphs if p.style.name=='Normal']
    if body[-len(expected):]!=expected and expected:
        # Headings separate body text, but source summaries precede it. Exact ordered body is required.
        raise ValueError('Summary text verification failed')
    receipt={'schema':1,'exporter':'merge-export-v1','summary':target.name,'total':len(jobs),
             'exported':len(done),'incomplete':len(pending),'sources':receipts,
             'docx_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    with target.with_suffix('.json').open('x',encoding='utf-8') as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
    return receipt


def merge(work):
    import aliyun_batch as batch
    work=Path(work).expanduser().resolve(strict=True);lock=work/'operation.lock'
    batch.acquire_runner_lock(lock,'merge')
    try:return build(batch.Store(paths.task_directory(work)/'tasks.json',backup=False))
    finally:batch.release_runner_lock(lock)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--work',required=True)
    print(json.dumps(merge(parser.parse_args().work),ensure_ascii=False))
