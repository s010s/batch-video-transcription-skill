"""Neutral paths for new batches, explicit compatibility for existing batches."""
import json
from pathlib import Path

def task_directory(work):
    work=Path(work)
    config=work/'batch.json'
    if config.is_file():
        name=json.loads(config.read_text()).get('task_directory')
        if name is not None:
            if name not in ('task-state','aliyun-batch'):raise ValueError('Invalid task directory')
            return work/name
    if (work/'aliyun-batch/tasks.json').is_file():return work/'aliyun-batch'
    return work/'task-state'

def neutral(tasks):return tasks.get('output_layout')=='neutral-v1'
def receipt_name(tasks):return '任务清单.json' if neutral(tasks) else '阿里批量任务清单.json'
def detail_name(tasks):return '识别明细' if neutral(tasks) else '阿里批量'
def ownership_name(tasks):return '.viewer-generated.json' if neutral(tasks) else '.aliyun-viewer-generated.json'


def validate_export(tasks):
    """Detect swapped generated directories before writes; legacy layouts are unchanged."""
    if tasks.get('output_identity'):
        path=Path(tasks['output_root'])
        if path.is_symlink():raise ValueError('Export directory is a symlink; refusing writes')
        st=path.stat()
        if [st.st_dev,st.st_ino]!=tasks['output_identity']:raise ValueError('Export directory identity changed')
