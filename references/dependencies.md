# Required dependencies

Python 3.10+, FFmpeg and ffprobe are required. Python runs orchestration and document export; FFmpeg extracts full-timeline audio. Local preparation needs no API key. Recognition needs network access and an eligible provider account. Development tests also use Node.js.

Check `python3 --version`, `python --version` or `py -3 --version`, then `ffmpeg -version` and `ffprobe -version`. Reuse compatible installations. Explain missing software, source and installation location; obtain permission before installation. Do not silently escalate privileges or modify global settings.

- **macOS:** [Python](https://www.python.org/downloads/macos/) and [FFmpeg's download page](https://ffmpeg.org/download.html). Use trusted package-manager sources if already available and approved. Match Apple Silicon or Intel architecture.
- **Windows:** [Python](https://www.python.org/downloads/windows/) and Windows builds linked by [FFmpeg](https://ffmpeg.org/download.html). Match x64/ARM64 and verify the distributor. Ensure Python, FFmpeg and ffprobe can be found. Do not bypass OS security warnings.
- **Linux:** prefer the distribution's official Python, venv and FFmpeg packages; system installation still requires permission.

Use a project virtual environment and `scripts/requirements-docx.lock`. The launchers ask before creating an environment or installing those Python packages. They do not bundle or install system runtimes.

Runtime bundling requires platform-specific builds, signatures, security updates and license review. FFmpeg's distribution obligations depend on build flags (including LGPL/GPL components), and codecs may have patent implications. The repository's MIT license does not relicense these dependencies.
