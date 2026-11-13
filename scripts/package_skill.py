"""Create an explicit-only host package without changing the source or installing it."""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = ('LICENSE', 'SKILL.md', 'README.md', 'README_CN.md', '.gitignore',
              'Start-Video-Transcription.command', 'Start-Video-Transcription.bat')
PACKAGE_FILES = ('agents/openai.yaml', 'references/dependencies.md', 'references/execution.md', 'references/host-packaging.md', 'references/operations.md', 'references/providers.md', 'scripts/aliyun_batch.py', 'scripts/aliyun_batch_state.py', 'scripts/aliyun_live.py', 'scripts/aliyun_review_html.py', 'scripts/aliyun_sample.py', 'scripts/app.py','scripts/folder_picker.py', 'scripts/batch_paths.py', 'scripts/check_tests.py', 'scripts/export_aliyun_viewer.py', 'scripts/export_interview_docx.py', 'scripts/make_demo.py', 'scripts/package_skill.py', 'scripts/prepare_audio.py', 'scripts/provider_contract.py', 'scripts/requirements-docx.lock', 'scripts/toolkit.py', 'scripts/ui.html', 'scripts/ui-v2.html', 'scripts/videolib.py', 'scripts/web/app.js', 'scripts/web/index.html', 'scripts/web/style.css', 'tests/fake_whisper.py', 'tests/test_aliyun_batch_state.py', 'tests/test_aliyun_html.py', 'tests/test_aliyun_live.py', 'tests/test_aliyun_sample.py', 'tests/test_app.py','tests/test_folder_picker.py', 'tests/test_package_skill.py', 'tests/test_portable_exports.py', 'tests/test_toolkit.py', 'tests/test_ui_v2.py', 'tests/test_videolib.py')


# Explicit runtime additions; never include batches, media or credentials.
PACKAGE_FILES += ('scripts/check_dependencies.py', 'scripts/workflow_state.py', 'scripts/merge_export.py')

def safe_source(name):
    source = ROOT / name
    if source.is_symlink() or any(p.is_symlink() for p in source.parents if p != ROOT and ROOT in p.parents):
        raise ValueError('Symbolic links are not allowed in packages')
    if ROOT.resolve() not in source.resolve().parents or not source.is_file():
        raise ValueError('Package source is missing or outside the source tree')
    return source

def package(host, output):
    if host not in ('codex', 'claude'):
        raise ValueError('Unsupported host')
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError('Destination exists; refusing to overwrite')
    if output == ROOT or ROOT in output.parents or output in ROOT.parents:
        raise ValueError('Destination must be separate from source')
    names = list(ROOT_FILES) + list(PACKAGE_FILES)
    # Ship all Python tests only, not arbitrary files in the tests directory.
    names += ['tests/test_dependencies.py','tests/test_merge_export.py','tests/test_no_words.py','tests/test_release_invariants.py','tests/test_safe_recovery.py']
    files = [safe_source(name) for name in dict.fromkeys(names)]
    if not all(f.is_file() for f in files):
        raise ValueError('Package is missing required files')
    skill = (ROOT / 'SKILL.md').read_text()
    if not skill.startswith('---\n') or '\n---\n' not in skill[4:]:
        raise ValueError('Invalid skill frontmatter')
    if host == 'claude':
        skill = skill.replace('---\n', '---\ndisable-model-invocation: true\n', 1)
    output.mkdir(parents=True)
    for source in files:
        target = output / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (output / 'SKILL.md').write_text(skill)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=('codex', 'claude'), required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(package(args.host, args.output))
