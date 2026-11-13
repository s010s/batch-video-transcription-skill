#!/usr/bin/env python3
"""Generate clearly labeled synthetic fixtures inside this project only."""
from pathlib import Path
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'demo' / '测试素材'


def generate(root=ROOT):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('测试素材生成需要已安装的 FFmpeg')
    root.mkdir(parents=True, exist_ok=True)
    for folder, sound in [('中文 空格', 'sine=frequency=440:sample_rate=16000'), ('嵌套/同名', 'anullsrc=r=16000:cl=mono')]:
        dest = root / folder / '示例.mp4'
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x173c36:s=640x360:r=24:d=5', '-f', 'lavfi', '-i', sound, '-t', '5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(dest)], check=True)
    subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x26384c:s=640x360:r=24:d=5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(root / '无音轨.mp4')], check=True)
    (root / '损坏文件.mp4').write_bytes(b'TEST DATA: intentionally corrupt video')
    (root / 'TEST_DATA.txt').write_text('全部为合成测试视频；正弦波不是语音，fake_whisper 输出虚拟文字。\n', encoding='utf-8')
    return root


if __name__ == '__main__':
    root = generate()
    extra = root / '跨视频 搜索' / '第二段.mp4'
    extra.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / '中文 空格' / '示例.mp4', extra)
    print(root)
