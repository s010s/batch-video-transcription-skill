import json,shutil,tempfile,subprocess,unittest,urllib.parse
from pathlib import Path
from unittest.mock import patch
import toolkit as t, videolib as v, aliyun_batch as b, aliyun_live as live,batch_paths as paths

class PortableExportTests(unittest.TestCase):
    def test_nested_special_names_move_and_excluded_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'media';folder=root/'nested # 字幕';folder.mkdir(parents=True)
            video=folder/'clip & 01.mp4'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=160x120:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],check=True)
            original=v.digest(video);work=Path(tmp)/'work';t.init(root,work);t.main(['prepare','--work',str(work)])
            store=b.Store(paths.task_directory(work)/'tasks.json');self.assertEqual(len(store.data['jobs']),1)
            job=next(iter(store.data['jobs'].values()));out=work/'mock-result';out.mkdir()
            raw={'transcripts':[{'sentences':[{'begin_time':0,'end_time':800,'text':'Synthetic test','speaker_id':0}]}]}
            live.export(raw,{'sample_id':job['id'],'source_relative_path':job['relative_path'],'offset_seconds':0,'duration_seconds':job['duration_seconds']},out)
            job.update(status='downloaded',result_dir=str(out));store.save();b.export_job(store,job);t.publish()
            export=store.output_root;self.assertTrue(export.is_relative_to(root.resolve()));self.assertEqual(export.name,'Transcription-Export')
            (export/'should-not-be-scanned.mp4').write_bytes(b'not-media')
            t.main(['prepare','--work',str(work)]);self.assertEqual(len(v.load(paths.task_directory(work)/'tasks.json')['jobs']),1)
            self.assertEqual(v.digest(video),original)
            for f in export.rglob('*'):
                self.assertNotIn('aliyun',f.name.lower());self.assertNotIn('阿里',f.name)
            moved=Path(tmp)/'moved # 素材';shutil.copytree(root,moved)
            dest=moved/export.name/'转写结果';data=json.loads((dest/'data.js').read_text().split('=',1)[1].strip().rstrip(';'))
            media=data['videos'][0]['media'];self.assertFalse(media.startswith(('file:','http')))
            target=(dest/urllib.parse.unquote(media)).resolve();self.assertTrue(target.is_file());self.assertEqual(v.digest(target),original)
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(target)]));self.assertGreater(float(info['format']['duration']),0)
            self.assertTrue((dest/'视频文字稿.html').is_file())
    def test_conflict_readonly_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();existing=root/'Transcription-Export';existing.mkdir();(existing/'keep').write_text('original')
            t.init(root,Path(tmp)/'work');self.assertEqual(v.load(Path(tmp)/'work/task-state/tasks.json')['output_root'],str((root/'Transcription-Export-2').resolve()));self.assertEqual((existing/'keep').read_text(),'original')
            with patch.object(Path,'mkdir',side_effect=PermissionError):
                with self.assertRaisesRegex(ValueError,'只读'):t.init(root,Path(tmp)/'another')
            out=root/'link';out.symlink_to(existing,target_is_directory=True)
            with self.assertRaises(ValueError):t.init(root,Path(tmp)/'third',out)
    def test_legacy_paths_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=Path(tmp);(w/'aliyun-batch').mkdir();(w/'aliyun-batch/tasks.json').write_text('{}');(w/'batch.json').write_text('{}')
            self.assertEqual(paths.task_directory(w),w/'aliyun-batch');self.assertEqual(paths.receipt_name({}),'阿里批量任务清单.json');self.assertEqual(paths.detail_name({}),'阿里批量')
    def test_selected_scope_stays_bound_to_original_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();(root/'one.mp4').write_bytes(b'one');(root/'two.mp4').write_bytes(b'two');work=Path(tmp)/'work'
            t.init(root,work,include_files=['one.mp4']);config=v.load(work/'batch.json')
            self.assertEqual(config['selected_sources'],['one.mp4'])
            lib=v.Library(root,work/'production-output');lib.scan(include=config['selected_sources'])
            self.assertEqual([x['relative_path'] for x in lib.read()['videos']],['one.mp4'])
            self.assertEqual(Path(config['root']),root.resolve())
            (Path(tmp)/'escape.mp4').write_bytes(b'outside')
            with self.assertRaises(ValueError):t.init(root,Path(tmp)/'other',include_files=['../escape.mp4'])
