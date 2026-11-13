"""Local Word authoring from existing normalized sentences and merged turns."""
import argparse
import json
from pathlib import Path, PurePosixPath
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

BASE=Path(__file__).resolve().parent

def timestamp(seconds):
    total=int(seconds+0.5);hours,total=divmod(total,3600);minutes,secs=divmod(total,60)
    return f'{hours:02}:{minutes:02}:{secs:02}'

def create(output,source=None):
    if not source:raise ValueError('必须明确指定本批source目录')
    source=Path(source)
    docdata=json.loads((source/'normalized.json').read_text());turns=json.loads((source/'turns.json').read_text())
    segments=docdata['segments'];relative=PurePosixPath(docdata['relative_path'])
    assert [text for t in turns for text in t['texts']]==[s['text'] for s in segments]
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('来源相对路径越界')
    document=Document();section=document.sections[0]
    section.page_width=Cm(21);section.page_height=Cm(29.7)
    section.top_margin=Cm(2.2);section.bottom_margin=Cm(2.2);section.left_margin=Cm(2.3);section.right_margin=Cm(2.3)
    for name,size in [('Normal',11),('Title',22),('Heading 2',12)]:
        style=document.styles[name];style.font.name='PingFang SC';style.font.size=Pt(size);style.font.color.rgb=RGBColor(0,0,0)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'PingFang SC')
    normal=document.styles['Normal'];normal.paragraph_format.line_spacing=1.35;normal.paragraph_format.space_after=Pt(9)
    info=document.add_paragraph('来源：'+str(relative));info.paragraph_format.space_after=Pt(8)
    if docdata.get('recognition_outcome')=='no_recognized_words':
        document.add_paragraph('本段服务未识别出文字。此说明不是对白转写，也不表示已确认视频中无人说话。')
    for turn in turns:
        speaker=segments[turn['sentence_indices'][0]]['speaker_id'];label='未知' if speaker is None else str(speaker)
        heading=document.add_paragraph(f'讲话人 {label}    {timestamp(turn["start"])}–{timestamp(turn["end"])}',style='Heading 2')
        heading.paragraph_format.keep_with_next=True;heading.paragraph_format.space_before=Pt(12);heading.paragraph_format.space_after=Pt(6)
        paragraph=document.add_paragraph(''.join(turn['texts']))
        paragraph.paragraph_format.widow_control=True
    document.core_properties.title=relative.stem
    document.core_properties.subject='采访发言段转写'
    document.core_properties.author='';document.core_properties.last_modified_by=''
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('目标Word已存在，拒绝覆盖')
    document.save(output)
    reopened=Document(output)
    # Exact paragraph preservation including spaces/punctuation; no rewrite of ASR text.
    body=[p.text for p in reopened.paragraphs]
    for turn in turns:assert ''.join(turn['texts']) in body
    print(json.dumps({'docx':str(output),'paragraph_turns':len(turns),'source_relative_path':str(relative),'word_relative_path':str(relative.with_suffix('.docx')),'network_requests':0},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--source');args=parser.parse_args();create(args.output,args.source)
