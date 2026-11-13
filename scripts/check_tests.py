"""Cross-platform test entry: python scripts/check_tests.py (no real ASR calls)."""
import os,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
os.environ['PYTHONPATH']=str(HERE)+os.pathsep+os.environ.get('PYTHONPATH','')
suite=unittest.defaultTestLoader.discover(str(HERE.parent/'tests'),pattern='test_*.py')
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
