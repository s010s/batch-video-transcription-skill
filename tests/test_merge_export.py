import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from docx import Document
import merge_export as m

class MergeExportTests(unittest.TestCase):
    def setup_batch(self,base):
        root=base/'media';root.mkdir();work=base/'work';work.mkdir();out=root/'Transcription-Export';out.mkdir();state=work/'task-state';state.mkdir()
        rs=root.stat();os=out.stat();jobs={}
        for name,text,outcome in [('b.mp4',' 原文，保留  空格。',None),('a.mp4','', 'no_recognized_words')]:
            video=root/name;video.write_bytes(b'synthetic');s=video.stat();result=work/name;result.mkdir()
            segments=[] if not text else [{'text':text,'speaker_id':0,'start':0.0,'end':1.0}]
            turns=[] if not text else [{'start':0.0,'end':1.0,'texts':[text],'sentence_indices':[0]}]
            normalized={'relative_path':name,'segments':segments}
            if outcome:normalized['recognition_outcome']=outcome
            (result/'normalized.json').write_text(json.dumps(normalized));(result/'turns.json').write_text(json.dumps(turns))
            jobs[name]={'relative_path':name,'status':'exported','source':{'size':s.st_size,'mtime_ns':s.st_mtime_ns},'result_dir':str(result),'duration_seconds':2.0,'task_id':'fake-'+name}
            job=jobs[name]
            word=out/(name+'.docx');word.write_bytes(b'synthetic-document')
            version=hashlib.sha256(json.dumps({'exporter':'word-html-v2','source':job['source'],'audio_sha256':None,
                'normalized_sha256':hashlib.sha256((result/'normalized.json').read_bytes()).hexdigest(),
                'turns_sha256':hashlib.sha256((result/'turns.json').read_bytes()).hexdigest()},sort_keys=True).encode()).hexdigest()
            job['export_receipt']={'version':version,'word_relative_path':word.name,'word_sha256':hashlib.sha256(word.read_bytes()).hexdigest()}
        data={'root':str(root),'root_identity':[rs.st_dev,rs.st_ino],'output_root':str(out),'output_identity':[os.st_dev,os.st_ino],'jobs':jobs}
        return SimpleNamespace(data=data,path=state/'tasks.json',disk=lambda:None,recovery_required=False),out
    def test_verbatim_empty_and_safe_versioning(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,out=self.setup_batch(Path(tmp));original=json.dumps(store.data,sort_keys=True)
            report=m.build(store);self.assertEqual(report['exported'],2)
            doc=Document(out/report['summary']);text=[p.text for p in doc.paragraphs]
            self.assertLess(text.index('a.mp4'),text.index('b.mp4'))
            self.assertIn(' 原文，保留  空格。',text)
            self.assertTrue(any('服务未识别出文字' in p for p in text))
            old=(out/report['summary']).read_bytes();again=m.build(store)
            self.assertNotEqual(report['summary'],again['summary']);self.assertEqual(old,(out/report['summary']).read_bytes())
            self.assertEqual(original,json.dumps(store.data,sort_keys=True))
    def test_incomplete_report_and_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,out=self.setup_batch(Path(tmp));store.data['jobs']['b.mp4']['status']='submission_uncertain'
            report=m.build(store);self.assertEqual(report['incomplete'],1)
            self.assertIn('b.mp4 — submission_uncertain',[p.text for p in Document(out/report['summary']).paragraphs])
            store.data['jobs']['b.mp4']['status']='exported'
            (Path(store.data['root'])/'b.mp4').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'fingerprint'):m.build(store)
    def test_result_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,out=self.setup_batch(Path(tmp));job=store.data['jobs']['b.mp4']
            p=Path(job['result_dir'])/'turns.json';turns=json.loads(p.read_text());turns[0]['texts']=['wrong'];p.write_text(json.dumps(turns))
            with self.assertRaisesRegex(ValueError,'mismatch'):m.build(store)

    def test_recovery_blocks_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,out=self.setup_batch(Path(tmp));store.recovery_required=True
            with self.assertRaisesRegex(ValueError,'recovery'):m.build(store)
            store.recovery_required=False
            (store.path.parent/'.pending-state.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'recovery'):m.build(store)
            self.assertFalse(list(out.glob('Transcript-Summary*')))
    def test_edited_word_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,out=self.setup_batch(Path(tmp));(out/'b.mp4.docx').write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):m.build(store)
            self.assertFalse(list(out.glob('Transcript-Summary*')))
    def test_coherent_result_edit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,out=self.setup_batch(Path(tmp));result=Path(store.data['jobs']['b.mp4']['result_dir'])
            n=json.loads((result/'normalized.json').read_text());t=json.loads((result/'turns.json').read_text())
            n['segments'][0]['text']='edited';t[0]['texts']=['edited']
            (result/'normalized.json').write_text(json.dumps(n));(result/'turns.json').write_text(json.dumps(t))
            with self.assertRaisesRegex(ValueError,'version mismatch'):m.build(store)
            self.assertFalse(list(out.glob('Transcript-Summary*')))
