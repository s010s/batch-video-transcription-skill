import tempfile,unittest
from pathlib import Path
from docx import Document
import toolkit as t,aliyun_batch as b,videolib as v
class NoWords(unittest.TestCase):
    def test_real_no_words_code_exports_empty_document_not_dialogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();src=root/'clip.mp4';src.write_bytes(b'source');work=Path(tmp)/'work';t.init(root,work);t.configure(work);s=b.Store(work/'task-state/tasks.json');j={'id':'x','status':'submitted','task_id':'retained-id','relative_path':'clip.mp4','duration_seconds':2,'source':v.source_stamp(src,False)};s.data['jobs']={'x':j};s.save()
            b.record_failure(s,j,{'output':{'task_status':'FAILED','code':'ASR_RESPONSE_HAVE_NO_WORDS'}},'cloud_FAILED')
            self.assertEqual(j['status'],'exported');self.assertEqual(j['task_id'],'retained-id');self.assertEqual(j['recognition_outcome'],'no_recognized_words');self.assertEqual(v.load(Path(j['result_dir'])/'normalized.json')['segments'],[])
            doc=Document(s.output_root/'转写结果明细/clip.docx');self.assertIn('服务未识别出文字',''.join(p.text for p in doc.paragraphs));self.assertEqual(s.summary()['failed'],0)
