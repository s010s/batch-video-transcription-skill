"""Offline startup checks; never installs software or changes PATH."""
import argparse
import importlib.metadata
import shutil
import sys
from pathlib import Path


def check_runtime(version=None, which=shutil.which):
    version = sys.version_info if version is None else version
    problems = []
    if tuple(version[:2]) < (3, 10):
        problems.append('Python 3.10 or newer is required. Install from https://www.python.org/downloads/.')
    for name in ('ffmpeg', 'ffprobe'):
        if not which(name):
            problems.append(name + ' is missing from PATH. See https://ffmpeg.org/download.html and references/dependencies.md; installation requires your permission.')
    return problems


def check_packages(lock=None, version=importlib.metadata.version):
    lock = lock or Path(__file__).with_name('requirements-docx.lock')
    problems = []
    for line in Path(lock).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, expected = line.split('==', 1)
        try:
            actual = version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = 'not installed'
        if actual != expected:
            problems.append('{}: required {}, found {}'.format(name, expected, actual))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-only', action='store_true')
    parser.add_argument('--packages-only', action='store_true')
    args = parser.parse_args()
    problems = []
    if not args.packages_only:
        problems += check_runtime()
    if not args.runtime_only:
        problems += check_packages()
    if problems:
        print('\n'.join(problems))
        return 1
    print('Dependency checks passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
