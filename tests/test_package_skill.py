import tempfile
import unittest
from pathlib import Path
import package_skill as p


class PackagingTests(unittest.TestCase):
    def test_explicit_only_host_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            for host in ('codex', 'claude'):
                out=p.package(host,Path(tmp)/host/'batch-video-transcription')
                text=(out/'SKILL.md').read_text()
                self.assertEqual('disable-model-invocation: true' in text,host=='claude')
                self.assertIn('allow_implicit_invocation: false',(out/'agents/openai.yaml').read_text())
                self.assertFalse((out/'.git').exists())
                self.assertFalse((out/'.venv').exists())
                self.assertTrue((out/'Start-Video-Transcription.bat').is_file())
                self.assertEqual((out/'scripts/toolkit.py').read_bytes(),(p.ROOT/'scripts/toolkit.py').read_bytes())
                with self.assertRaises(ValueError):p.package(host,out)

    def test_reject_invalid_host_or_in_source_destination(self):
        with self.assertRaises(ValueError):p.package('other','/tmp/unused-host-package')
        with self.assertRaises(ValueError):p.package('codex',p.ROOT/'generated')
