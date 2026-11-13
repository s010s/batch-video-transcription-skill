import unittest,tempfile,subprocess
from pathlib import Path
from unittest.mock import patch
import folder_picker,app,toolkit as t
class PickerTests(unittest.TestCase):
    def test_native_success_and_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            for platform in ('darwin','win32'):
                with patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,d,'')) as run:
                    self.assertEqual(folder_picker.choose_directory(platform),Path(d).resolve())
                    self.assertNotIn('shell',run.call_args.kwargs)
            with patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','User canceled (-128)')):
                self.assertIsNone(folder_picker.choose_directory('darwin'))
    def test_failure_no_install_or_raw_error(self):
        with patch.object(subprocess,'run',side_effect=OSError('private info')):
            with self.assertRaisesRegex(ValueError,'手动'):folder_picker.choose_directory('win32')
        with self.assertRaisesRegex(ValueError,'手动'):folder_picker.choose_directory('linux')
    def test_choose_does_not_create_or_prepare(self):
        with tempfile.TemporaryDirectory() as d:
            state=app.AppState()
            with patch.object(folder_picker,'choose_directory',return_value=Path(d)),patch.object(t,'init') as init:
                result=state.choose_source();init.assert_not_called();self.assertFalse(Path(result['work']).exists())
                self.assertEqual(result['root'],d)
            state.busy=True
            with self.assertRaises(ValueError):state.choose_source()
    def test_conflict_requires_explicit_new(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();(root/'Transcription-Export').mkdir();work=Path(d)/'work';state=app.AppState()
            with patch.object(t,'init') as init:
                state._execute('prepare',{'root':str(root),'work':str(work)})
                init.assert_not_called()
            self.assertIn('已存在',state.message)
