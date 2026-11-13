"""Offline batch state groundwork. No network client or real submission entry."""
import hashlib
import json
from pathlib import Path
import sqlite3

class BatchState:
    def __init__(self,path,root):
        self.path=Path(path);self.root=Path(root).resolve(strict=True)
        st=self.root.stat();identity=json.dumps([str(self.root),st.st_dev,st.st_ino])
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,fingerprint TEXT,status TEXT,task_id TEXT,result_path TEXT,result_hash TEXT)')
        old=self.setting('root_identity')
        if old and old!=identity:raise ValueError('硬盘/素材根身份改变，暂停')
        self.set('root_identity',identity)
        if self.setting('free_only') is None:self.set('free_only','true')
        if self.setting('paused') is None:self.set('paused','false')
    def setting(self,key):
        row=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return row[0] if row else None
    def set(self,key,value):self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,value))
    def disk_check(self):
        try:
            s=self.root.stat();identity=json.dumps([str(self.root),s.st_dev,s.st_ino])
            if identity!=self.setting('root_identity'):raise OSError('identity mismatch')
        except OSError:
            self.pause('disk_missing_or_changed');raise ValueError('硬盘断开或身份改变，停止新读写；不创建挂载目录') from None
    def add(self,id,fingerprint):
        old=self.db.execute('SELECT fingerprint FROM jobs WHERE id=?',(id,)).fetchone()
        if old and old[0]!=fingerprint:raise ValueError('文件/模型参数指纹改变，需新任务版本，不能复用')
        self.db.execute('INSERT OR IGNORE INTO jobs(id,fingerprint,status) VALUES (?,?,?)',(id,fingerprint,'pending'))
    def pause(self,reason='user_pause'):
        self.set('paused','true');self.set('pause_reason',reason)
    def resume(self):
        self.disk_check()
        if self.setting('pause_reason')=='free_quota_exhausted':raise ValueError('免费额度已耗尽，禁止新提交')
        self.set('paused','false')
    def provider_error(self,code):
        if 'AllocationQuota' in code or 'FreeTierOnly' in code:
            self.pause('free_quota_exhausted');return 'pause_new_submissions'
        # Network errors leave submission_uncertain or submitted untouched.
        return 'retain_existing_task_no_resubmit'
    def reserve_submission(self,id):
        self.disk_check();self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.setting('paused')=='true':raise ValueError('已暂停新提交')
            active=self.db.execute("SELECT count(*) FROM jobs WHERE status='submission_uncertain'").fetchone()[0]
            if active>=3:raise ValueError('并发上限3')
            row=self.db.execute('SELECT status FROM jobs WHERE id=?',(id,)).fetchone()
            if not row or row[0]!='pending':raise ValueError('禁止重复提交或盲重试')
            self.db.execute("UPDATE jobs SET status='submission_uncertain' WHERE id=?",(id,));self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
    def record_task(self,id,task_id):
        if not isinstance(task_id,str) or not task_id or len(task_id)>100:raise ValueError('无效任务ID')
        self.db.execute("UPDATE jobs SET task_id=?,status='submitted' WHERE id=? AND status='submission_uncertain'",(task_id,id))
    def downloaded(self,id,path):
        path=Path(path);data=path.read_bytes();json.loads(data)
        # Only a real local result file can establish downloaded state; no signed URL.
        self.db.execute("UPDATE jobs SET status='downloaded',result_path=?,result_hash=? WHERE id=? AND task_id IS NOT NULL",(str(path.resolve()),hashlib.sha256(data).hexdigest(),id))
    def next_actions(self,mode="collect"):
        if mode not in ("collect","submit-all"):raise ValueError("未知阶段")
        rows=self.db.execute('SELECT id,status,task_id,result_path FROM jobs ORDER BY id').fetchall()
        existing=[{'id':r[0],'action':'query_and_download','task_id':r[2]} for r in rows if r[1]=='submitted']
        uncertain=[{'id':r[0],'action':'manual_reconcile_no_resubmit'} for r in rows if r[1]=='submission_uncertain']
        pending=[] if mode=='collect' or self.setting('paused')=='true' else [{'id':r[0],'action':'upload_and_submit_without_waiting_for_recognition'} for r in rows if r[1]=='pending']
        return existing+uncertain+pending
    def report(self):
        rows=self.db.execute('SELECT status,task_id,result_path FROM jobs').fetchall()
        return {'total':len(rows),'submitted_with_id':sum(bool(r[1]) for r in rows),
                'not_submitted':sum(r[0]=='pending' for r in rows),
                'no_audio':sum(r[0]=='no_audio' for r in rows),
                'failed':sum(r[0]=='failed' for r in rows),
                'uncertain_without_id':sum(r[0]=='submission_uncertain' and not r[1] for r in rows),
                'downloaded':sum(r[0]=='downloaded' and bool(r[2]) for r in rows),
                'with_id_not_downloaded':sum(bool(r[1]) and r[0]!='downloaded' for r in rows),
                'paused_new_submissions':self.setting('paused')=='true'}
    def close(self):self.db.close()
