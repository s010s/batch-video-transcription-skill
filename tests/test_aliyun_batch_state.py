import json
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aliyun_batch_state import BatchState

class StateTests(unittest.TestCase):
    def test_pause_resume_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'素材';root.mkdir();db=Path(d)/'state.sqlite'
            s=BatchState(db,root)
            for id in 'ABCD':s.add(id,'fp-'+id)
            for id in 'ABC':s.reserve_submission(id)
            with self.assertRaises(ValueError):s.reserve_submission('D')
            s.record_task('B','task-b');s.pause();s.close()
            s=BatchState(db,root);self.assertEqual(s.next_actions()[0]['task_id'],'task-b')
            s.resume()
            with self.assertRaises(ValueError):s.reserve_submission('B')
            result=Path(d)/'result.json';result.write_text(json.dumps({'transcripts':[]}));s.downloaded('B',result)
            s.reserve_submission('D')
            with self.assertRaises(ValueError):s.add('B','changed')
            s.provider_error('AllocationQuota.FreeTierOnly');self.assertEqual(s.setting('paused'),'true')
            with self.assertRaises(ValueError):s.resume()
            self.assertFalse(any(x['action']=='upload_and_submit_without_waiting_for_recognition' for x in s.next_actions()))
            s.close()
    def test_submit_all_does_not_wait_for_recognition(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'素材';root.mkdir();s=BatchState(Path(d)/'state.sqlite',root)
            for id in 'ABCD':s.add(id,'fp-'+id)
            for id in 'ABC':s.reserve_submission(id)
            for id in 'ABC':s.record_task(id,'task-'+id)
            # A/B/C may still be RUNNING; their IDs free submission slots.
            s.reserve_submission('D');s.record_task('D','task-D')
            self.assertEqual(s.report()['submitted_with_id'],4)
            self.assertEqual(s.report()['with_id_not_downloaded'],4)
            self.assertTrue(all(x['action']=='query_and_download' for x in s.next_actions('collect')))
            s.pause('user_leaving_offline')
            self.assertEqual(len(s.next_actions('collect')),4)
            s.close()
    def test_disk_missing_no_recreate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'素材';root.mkdir();s=BatchState(Path(d)/'state.sqlite',root);s.add('A','fp');root.rmdir()
            with self.assertRaises(ValueError):s.reserve_submission('A')
            self.assertFalse(root.exists());self.assertEqual(s.setting('paused'),'true');s.close()

if __name__=='__main__':unittest.main()
