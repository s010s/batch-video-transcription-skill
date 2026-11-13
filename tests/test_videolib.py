import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import videolib as v
from make_demo import generate


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires installed FFmpeg')
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.root = generate(cls.base / '中文 root')
        cls.output = cls.base / 'output'
        cls.fake = cls.base / 'fake_whisper'
        shutil.copyfile(Path(__file__).parent / 'fake_whisper.py', cls.fake)
        cls.fake.chmod(0o755)
        cls.model = cls.base / 'dummy-model.bin'
        cls.model.write_bytes(b'TEST MODEL - NOT REAL')
        cls.lib = v.Library(cls.root, cls.output)
        cls.argv = ['transcribe', '--root', str(cls.root), '--output', str(cls.output), '--whisper-cli', str(cls.fake), '--model', str(cls.model)]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def call(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = v.main(argv)
        return code, [json.loads(s) for s in out.getvalue().splitlines()]

    def test_01_pipeline_and_incremental(self):
        original = {str(p): v.digest(p) for p in self.root.rglob('*.mp4')}
        code, events = self.call(self.argv)
        self.assertEqual(code, 1)  # one bad file does not block other items
        obj = self.lib.read()
        statuses = {x['relative_path']: x['status'] for x in obj['videos']}
        self.assertEqual(statuses['中文 空格/示例.mp4'], 'done')
        self.assertEqual(statuses['嵌套/同名/示例.mp4'], 'no_speech')
        self.assertEqual(statuses['无音轨.mp4'], 'no_audio')
        self.assertEqual(statuses['损坏文件.mp4'], 'failed')
        self.assertEqual(len({x['id'] for x in obj['videos']}), 4)
        import wave
        item = next(x for x in obj['videos'] if x['status'] == 'done')
        with wave.open(str(self.lib.store / item['artifacts']['audio.wav'])) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
        self.assertTrue(item['test_data'])
        self.assertEqual(original, {str(p): v.digest(p) for p in self.root.rglob('*.mp4')})
        _, events = self.call(self.argv)
        self.assertEqual(sum(x['status'] == 'cached' for x in events), 3)
        # Damaged output never reuses old results.
        (self.lib.store / item['artifacts']['transcript.txt']).write_text('tampered')
        _, events = self.call(self.argv + ['--id', item['id']])
        self.assertFalse(any(x['status'] == 'cached' for x in events))
        # A different model invalidates cache.
        self.model.write_bytes(b'changed test model')
        _, events = self.call(self.argv + ['--id', item['id']])
        self.assertFalse(any(x['status'] == 'cached' for x in events))
        # An engine binary change invalidates cache even if its reported version is unchanged.
        with self.fake.open('a') as f:
            f.write('\n# engine changed\n')
        _, events = self.call(self.argv + ['--id', item['id']])
        self.assertFalse(any(x['status'] == 'cached' for x in events))
        code, events = self.call(['search', '--root', str(self.root), '--output', str(self.output), '--query', '搜索', '--filename', '中文 空格'])
        self.assertEqual(code, 0)
        self.assertEqual(events[0]['count'], 1)
        self.assertEqual(events[0]['hits'][0]['start'], 2)

    def test_02_hash_invalidation_and_removed_file(self):
        target = self.root / '新文件.mp4'
        target.write_bytes(b'abcd')
        with self.lib.lock():
            obj = self.lib.scan()
        item = next(x for x in obj['videos'] if x['relative_path'] == target.name)
        item.update(status='done', segments=[{'start': 0, 'end': 1, 'text': 'stale'}])
        self.lib.save(obj)
        stamp = target.stat()
        target.write_bytes(b'wxyz')
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.lib.lock():
            changed = self.lib.scan()
        fresh = next(x for x in changed['videos'] if x['relative_path'] == target.name)
        self.assertEqual(fresh['status'], 'done')  # scan deliberately uses metadata only
        self.assertIn('segments', fresh)
        self.assertNotEqual(v.source_stamp(target)['sha256'], item['source'].get('sha256'))
        target.unlink()
        with self.lib.lock():
            self.assertNotIn(target.name, [i['relative_path'] for i in self.lib.scan()['videos']])

    def test_03_boundaries_and_root_identity(self):
        other = self.base / 'other'
        other.mkdir(exist_ok=True)
        (other / 'secret.mp4').write_bytes(b'secret')
        link = self.root / '越界.mp4'
        link.symlink_to(other / 'secret.mp4')
        with self.lib.lock():
            obj = self.lib.scan()
        item = next(i for i in obj['videos'] if i['relative_path'] == link.name)
        self.assertEqual(item['status'], 'failed')
        with self.assertRaises(ValueError):
            self.lib.source(item)
        with self.assertRaises(ValueError):
            self.lib.source({'relative_path': '../other/secret.mp4'})
        link.unlink()
        self.assertNotEqual(self.lib.root_id, v.Library(other, self.output).root_id)
        with self.assertRaises(ValueError):
            v.Library(self.root, self.root)

    def test_04_http_security_and_range(self):
        token = 'test-secret'
        server = ThreadingHTTPServer(('127.0.0.1', 0), v.handler_for(self.lib, token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, headers=None, method='GET'):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request(method, path, headers=headers or {})
            r = conn.getresponse(); result = (r.status, dict(r.getheaders()), r.read()); conn.close()
            return result
        try:
            self.assertEqual(request('/api/library')[0], 403)
            self.assertEqual(request('/api/library?token='+token, {'Origin': 'https://evil.test'})[0], 403)
            self.assertEqual(request('/api/library?token='+token, {'Sec-Fetch-Site': 'cross-site'})[0], 403)
            self.assertEqual(request('/api/library?token='+token, {'Host': 'evil.test'})[0], 403)
            self.assertEqual(request('/api/library?token='+token, method='POST')[0], 405)
            status, headers, body = request('/api/library?token='+token)
            self.assertEqual(status, 200)
            self.assertNotIn(str(self.root).encode(), body)
            self.assertNotIn('Access-Control-Allow-Origin', headers)
            item = next(i for i in self.lib.read()['videos'] if i['relative_path'] == '中文 空格/示例.mp4')
            media = '/media/'+item['id']+'?token='+token
            status, headers, body = request(media, {'Range': 'bytes=10-19'})
            self.assertEqual(status, 206)
            self.assertEqual(body, self.lib.source(item).read_bytes()[10:20])
            self.assertEqual(request(media, {'Range': 'bytes=-5'})[2], self.lib.source(item).read_bytes()[-5:])
            self.assertEqual(request(media, {'Range': 'bytes=999999999-'})[0], 416)
            self.assertEqual(request(media, {'Range': 'bytes=0-1,3-4'})[0], 416)
            self.assertEqual(request('/media/../secret?token='+token)[0], 404)
            self.assertEqual(request('/media/%2e%2e/secret?token='+token)[0], 404)
            self.assertEqual(request(media, method='HEAD')[2], b'')
            # Symlink swapped after indexing is rechecked for each request.
            swap = self.lib.source(item)
            backup = swap.with_suffix('.backup')
            swap.rename(backup)
            try:
                swap.symlink_to(self.base / 'dummy-model.bin')
                self.assertEqual(request(media)[0], 404)
            finally:
                swap.unlink(); backup.rename(swap)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_05_audio_delayed_start(self):
        import wave
        root = self.base / 'delayed-root'; root.mkdir()
        target = root / '延迟音轨.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=320x180:r=24:d=5', '-itsoffset', '2', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000:duration=3', '-c:v', 'libx264', '-c:a', 'aac', str(target)], check=True)
        args = self.argv.copy(); args[args.index('--root')+1] = str(root)
        code, _ = self.call(args)
        self.assertEqual(code, 0)
        lib = v.Library(root, self.output); item = lib.read()['videos'][0]
        with wave.open(str(lib.store / item['artifacts']['audio.wav'])) as wav:
            import array
            first = array.array('h', wav.readframes(16000))
            self.assertLess(max(abs(s) for s in first), 10)
            self.assertGreaterEqual(wav.getnframes()/16000, 4.9)

    def test_06_cancel_and_resume(self):
        item = next(i for i in self.lib.read()['videos'] if i['relative_path'] == '中文 空格/示例.mp4')
        real_run = v.run
        def cancel_engine(cmd, *args, **kwargs):
            if '-m' in cmd and '-ojf' in cmd:
                raise KeyboardInterrupt
            return real_run(cmd, *args, **kwargs)
        with patch.object(v, 'run', side_effect=cancel_engine):
            code, _ = self.call(self.argv + ['--id', item['id'], '--force'])
        self.assertEqual(code, 130)
        interrupted = next(i for i in self.lib.read()['videos'] if i['id'] == item['id'])
        self.assertEqual(interrupted['status'], 'interrupted')
        self.assertEqual(interrupted['segments'], [])
        self.assertFalse((self.lib.store / '.writer.lock').exists())
        self.assertEqual(list((self.lib.store / '.work').iterdir()), [])
        code, _ = self.call(self.argv + ['--id', item['id']])
        self.assertEqual(code, 0)
        self.assertEqual(next(i for i in self.lib.read()['videos'] if i['id'] == item['id'])['status'], 'done')

    def test_07_static_export_and_relocation(self):
        from urllib.parse import unquote
        obj = self.lib.read()
        item = next(i for i in obj['videos'] if i['status'] == 'done')
        item['segments'][0]['text'] = '</script><script>alert(1)</script> 中文 & 空格'
        self.lib.save(obj)
        originals = {str(p): v.digest(p) for p in self.root.rglob('*.mp4')}
        args = ['export-static', '--root', str(self.root), '--output', str(self.output)]
        code, events = self.call(args)
        self.assertEqual(code, 0)
        self.assertEqual(events[0]['copied_video_bytes'], 0)
        dest = self.root / '转写结果'
        data_script = (dest / 'data.js').read_text()
        self.assertNotIn('<script>', data_script)
        self.assertNotIn(str(self.root), data_script)
        data = json.loads(data_script.removeprefix('window.VIDEO_LIBRARY = ').strip().removesuffix(';'))
        html = (dest / '视频文字稿.html').read_text()
        self.assertNotIn('token=', html)
        self.assertIn('src="data.js"', html)
        self.assertNotIn('type="module"', html)
        self.assertNotIn('http', html)
        self.assertEqual(originals, {str(p): v.digest(p) for p in self.root.rglob('*.mp4')})
        # Only synthetic fixtures are copied for this relocation check.
        moved = self.base / '模拟 Windows 硬盘 & 空格'
        shutil.copytree(self.root, moved)
        for row in data['videos']:
            if row.get('media'):
                target = (moved / '转写结果' / unquote(row['media'])).resolve()
                self.assertTrue(target.is_file())
                self.assertTrue(target.is_relative_to(moved.resolve()))
        with patch.object(v.Library, 'source', side_effect=ValueError('outside')):
            code, _ = self.call(args)
        self.assertEqual(code, 0)
        restricted = json.loads((dest / 'data.js').read_text().removeprefix('window.VIDEO_LIBRARY = ').strip().removesuffix(';'))
        self.assertTrue(all('media' not in row for row in restricted['videos']))
        unknown = self.root / '非空目录'
        unknown.mkdir(); (unknown / 'index.html').write_text('owned by user')
        code, _ = self.call(args + ['--destination', str(unknown)])
        self.assertEqual(code, 1)
        self.assertEqual((unknown / 'index.html').read_text(), 'owned by user')
        # Default destination symlink must not escape the chosen root.
        shutil.rmtree(dest)
        dest.symlink_to(self.base / 'other', target_is_directory=True)
        try:
            self.assertEqual(self.call(args)[0], 1)
        finally:
            dest.unlink()

    def test_08_sidecar_protection_and_summary_contract(self):
        root = self.base / '摘要与同名测试'; root.mkdir()
        src = self.root / '中文 空格' / '示例.mp4'
        for name in ('采访.mp4', '采访.mov'):
            shutil.copyfile(src, root / name)
        args = self.argv.copy(); args[args.index('--root') + 1] = str(root)
        self.assertEqual(self.call(args)[0], 0)
        lib = v.Library(root, self.output)
        item = next(i for i in lib.read()['videos'] if i['relative_path']=='采访.mp4')
        summary_args = ['summarize', '--root', str(root), '--output', str(self.output), '--id', item['id']]
        code, events = self.call(summary_args)
        self.assertEqual(code, 0); self.assertFalse(events[0]['model_called'])
        s = item['segments'][0]
        doc = {'id':item['id'], 'transcript_sha256':v.transcript_digest(item), 'overview':'【测试摘要】介绍本地素材库。',
               'topics':[{'text':'本地素材库', 'evidence_segment_indices':[0]}],
               'quotes':[{'segment_index':0, **{k:s[k] for k in ('text','start','end')}}], 'limitations':['文字来自测试引擎。']}
        imported = self.base / 'summary-result.json'; v.atomic_json(imported, doc)
        self.assertEqual(self.call(summary_args + ['--import', str(imported)])[0], 0)
        export = ['export-static','--root',str(root),'--output',str(self.output),'--sidecars']
        self.assertEqual(self.call(export)[0], 0)
        folder = root / '转写结果'
        self.assertTrue((folder / '采访.mp4.txt').exists()); self.assertTrue((folder / '采访.mov.txt').exists())
        self.assertTrue((folder / '采访.mp4.时间码.txt').exists())
        self.assertTrue((folder / '采访.mp4.srt').exists())
        self.assertIn('AI 摘要', (folder / '采访.mp4-摘要.txt').read_text())
        self.assertEqual((folder / '采访.mp4.txt').read_text(), '\n'.join(s['text'] for s in item['segments'])+'\n')
        self.assertEqual(list(folder.glob('*.wav')), [])
        changed = folder / '采访.mp4.txt'; changed.write_text('用户手改文字')
        code, events = self.call(export); self.assertEqual(code, 0)
        self.assertEqual(changed.read_text(), '用户手改文字'); self.assertTrue(events[0]['warnings'])
        # Exact quotes and timestamps cannot be fabricated at import.
        doc['quotes'][0]['text'] = '编造原话'; v.atomic_json(imported, doc)
        self.assertEqual(self.call(summary_args + ['--import', str(imported)])[0], 1)
        obj = lib.read(); changed_item = next(i for i in obj['videos'] if i['id']==item['id']); changed_item['segments'][0]['text'] = '逐字稿已改变'; lib.save(obj)
        self.assertEqual(v.summary_view(changed_item)['status'], 'stale')
        self.assertEqual(self.call(export)[0], 0)
        self.assertIn('已过期', (folder / '采访.mp4-摘要.txt').read_text())

    def test_09_report_metadata_only_and_optional_strict_hash(self):
        with patch.object(v, 'digest', side_effect=AssertionError('report must not read full content hashes')):
            code, events = self.call(['report', '--root', str(self.root), '--output', str(self.output)])
        self.assertEqual(code, 0)
        self.assertEqual(events[0]['video_count'], 4)
        self.assertEqual(events[0]['no_audio_count'], 1)
        self.assertEqual(events[0]['unknown_duration_count'], 1)
        self.assertFalse(events[0]['content_hash_read'])
        root = self.base / '严格哈希测试'; root.mkdir()
        target = root / '例子.mp4'; shutil.copyfile(self.root / '中文 空格' / '示例.mp4', target)
        args = self.argv.copy(); args[args.index('--root')+1] = str(root); args += ['--verify-source-hash']
        self.assertEqual(self.call(args)[0], 0)
        _, events = self.call(args); self.assertTrue(any(e['status']=='cached' for e in events))
        before = target.stat(); content=bytearray(target.read_bytes()); content[-20]^=1; target.write_bytes(content)
        os.utime(target, ns=(before.st_atime_ns,before.st_mtime_ns))
        _, events = self.call(args)
        self.assertFalse(any(e['status']=='cached' for e in events))

    def test_10_aux_paths_protection_io_pause_resume(self):
        from urllib.parse import unquote
        root=self.base/'最终布局 # %'; root.mkdir()
        folder=root/'中文 空格 # %'; folder.mkdir()
        source=folder/'采访 # 100%.mp4'
        shutil.copyfile(self.root/'中文 空格'/'示例.mp4',source)
        (folder/'._采访 # 100%.mp4').write_bytes(b'AppleDouble auxiliary')
        args=self.argv.copy();args[args.index('--root')+1]=str(root)
        self.assertEqual(self.call(args)[0],0)
        lib=v.Library(root,self.output);self.assertEqual(len(lib.read()['videos']),1)
        item=lib.read()['videos'][0]
        txt=lib.store/item['artifacts']['transcript.txt'];txt.write_text('本机手改，不能覆盖')
        code,events=self.call(args+['--force']);self.assertEqual(code,0)
        self.assertEqual(txt.read_text(),'本机手改，不能覆盖');self.assertTrue(events[-1]['warnings'])
        export=['export-static','--root',str(root),'--output',str(self.output)]
        self.assertEqual(self.call(export)[0],0)
        dest=root/'转写结果';entry=dest/'视频文字稿.html';self.assertTrue(entry.exists())
        self.assertFalse((root/'视频文字稿.html').exists());self.assertFalse((folder/'文字稿').exists())
        result_txt=dest/source.relative_to(root).parent/(source.name+'.txt')
        result_txt.write_text('交付手改，不能覆盖')
        code,events=self.call(export);self.assertEqual(code,0);self.assertTrue(events[0]['warnings'])
        self.assertEqual(result_txt.read_text(),'交付手改，不能覆盖')
        data=json.loads((dest/'data.js').read_text().removeprefix('window.VIDEO_LIBRARY = ').strip().removesuffix(';'))
        url=data['videos'][0]['media'];self.assertIn('%23',url);self.assertIn('%25',url);self.assertIn('%20',url)
        self.assertNotIn(str(root),entry.read_text());self.assertNotIn('/Volumes', (dest/'data.js').read_text())
        moved=self.base/'盘符搬移模拟';shutil.copytree(root,moved)
        self.assertTrue((moved/'转写结果'/unquote(url)).resolve().is_file())
        real_run=v.run
        def failing(cmd,*a,**kw):
            if '-copyts' in cmd:raise v.SourceIOPause('Input/output error')
            return real_run(cmd,*a,**kw)
        with patch.object(v,'run',side_effect=failing):
            self.assertEqual(self.call(args+['--force'])[0],3)
        self.assertEqual(lib.read()['batch_status'],'paused_io');self.assertFalse((lib.store/'.writer.lock').exists())
        self.assertEqual(self.call(args)[0],0)
        with patch.object(v,'probe_info',side_effect=v.SourceIOPause('disk lost')):
            # Force probe to run again while preserving all previously completed records.
            before=lib.read();before['videos'][0].pop('media_info',None);lib.save(before)
            self.assertEqual(self.call(['scan','--root',str(root),'--output',str(self.output)])[0],3)
        self.assertEqual(lib.read()['videos'][0]['status'],'done')


class UnitTests(unittest.TestCase):
    def test_normalization_and_timecodes(self):
        self.assertEqual(v.normalize({'transcription':[{'offsets':{'from':1230,'to':2500},'text':'中文'}]})[0]['start'], 1.23)
        self.assertEqual(v.normalize({'transcription': []}), [])
        for raw in (None, {}, {'transcription':[{'offsets':{'from':-1,'to':2}}]}):
            with self.assertRaises(ValueError): v.normalize(raw)
        self.assertEqual(v.timecode(3661.123), '01:01:01,123')

    def test_windows_spawn_cleanup_branch(self):
        from unittest.mock import MagicMock
        proc = MagicMock(); proc.poll.return_value = None; proc.pid = 12345
        with patch.object(v.os, 'name', 'nt'), patch.object(v.subprocess, 'run') as call:
            v.stop_owned(proc)
        call.assert_called_once_with(['taskkill', '/PID', '12345', '/T', '/F'], capture_output=True)
        proc.wait.assert_called_once_with(timeout=3)

    @unittest.skipIf(os.name == 'nt', 'POSIX process-group integration')
    def test_timeout_cleans_owned_group(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / 'child.pid'
            script = "import subprocess,time,pathlib; p=subprocess.Popen(['sleep','120']); pathlib.Path("+repr(str(marker))+").write_text(str(p.pid)); time.sleep(120)"
            with self.assertRaises(subprocess.TimeoutExpired):
                v.run([sys.executable, '-c', script], timeout=0.5)
            pid = int(marker.read_text())
            # A reaped or zombie child is no longer running work; ps state is authoritative here.
            try:status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
            except PermissionError:self.skipTest('sandbox denies ps; owned-child OS-state verification unavailable')
            self.assertTrue(not status or status.startswith('Z'), status)


if __name__ == '__main__':
    unittest.main()
