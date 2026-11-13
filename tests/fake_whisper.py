#!/usr/bin/env python3
"""TEST ONLY. Simulates whisper-cli output; never performs speech recognition."""
import json
from pathlib import Path
import sys
import wave

if '--version' in sys.argv:
    print('TEST fake-whisper 1.0 (not a speech engine)')
    sys.exit(0)
args = sys.argv
with wave.open(args[args.index('-f') + 1]) as wav:
    frames = wav.readframes(wav.getnframes())
    duration = wav.getnframes() / wav.getframerate()
silent = not any(frames)
rows = [] if silent else [
    {'offsets': {'from': 0, 'to': 2000}, 'text': '这是测试数据，欢迎使用本地素材库。'},
    {'offsets': {'from': 2000, 'to': int(duration * 1000)}, 'text': '点击文字跳转时间，搜索多个视频。 <img src=x onerror=alert(1)>'}
]
Path(args[args.index('-of') + 1] + '.json').write_text(json.dumps({'test_data': True, 'transcription': rows}, ensure_ascii=False), encoding='utf-8')
