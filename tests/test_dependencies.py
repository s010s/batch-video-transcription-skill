import importlib.metadata
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import check_dependencies as d
import package_skill as p


class DependencyTests(unittest.TestCase):
    def test_runtime_version_and_binaries(self):
        self.assertEqual(d.check_runtime((3, 10), lambda name: '/bin/' + name), [])
        self.assertEqual(len(d.check_runtime((3, 9), lambda name: None)), 3)

    def test_exact_versions_and_missing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'lock'
            lock.write_text('one==1.0\ntwo==2.0\n')
            self.assertEqual(d.check_packages(lock, lambda n: {'one':'1.0','two':'2.0'}[n]), [])
            self.assertEqual(len(d.check_packages(lock, lambda n: 'old')), 2)
            def missing(name):
                raise importlib.metadata.PackageNotFoundError(name)
            self.assertEqual(len(d.check_packages(lock, missing)), 2)

    def test_package_rejects_links_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            root.mkdir()
            outside = Path(tmp) / 'private.txt'
            outside.write_text('synthetic')
            (root / 'linked').symlink_to(outside)
            (root / 'folder').symlink_to(Path(tmp), target_is_directory=True)
            with patch.object(p, 'ROOT', root):
                for name in ('linked', '../private.txt', 'folder/private.txt'):
                    with self.assertRaises(ValueError):
                        p.safe_source(name)

    def test_launchers_preflight_before_app(self):
        root = Path(__file__).resolve().parent.parent
        for name in ('Start-Video-Transcription.command', 'Start-Video-Transcription.bat'):
            text = (root / name).read_text()
            self.assertLess(text.index('check_dependencies.py'), text.index('app.py'))
            self.assertIn('from PyPI', text)
        bat = (root / 'Start-Video-Transcription.bat').read_text()
        self.assertIn('where py', bat)
        self.assertIn('where python', bat)
