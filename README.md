# Batch Video Transcription

English | [简体中文](README_CN.md)

Turn a folder of videos into timestamped transcripts, speaker segments, Word documents, subtitles, and a searchable local HTML viewer. Use the local interface directly or explicitly invoke the skill from an AI agent.

- Keep original videos unchanged; extract full-timeline audio locally.
- Review the file list, duration, service destination, and estimated cost before upload.
- Store deliverables in `Transcription-Export` under the media folder, with runtime state in a separate work folder.
- Resume a batch using its saved task IDs and cost reservations rather than starting over.
- Export individual documents and a combined Word summary without rewriting recognized text.

**Current provider: Alibaba Cloud Beijing Fun-ASR only.** The toolkit has an extension contract, not additional working providers. Recognition uploads audio to the service and may incur charges. Preparation and document export are local. The current interface and transcript labels are Chinese; English documentation does not imply an English UI or support for every recognition language.

## Requirements

- Python 3.10 or newer
- FFmpeg and ffprobe on `PATH`
- Network access and a compatible provider account for recognition
- Node.js for the development test suite

Python and FFmpeg are **required but not bundled**. Check existing installations before installing anything. AI agents must explain and obtain permission for missing software, using official or trusted distribution sources. See [dependency setup](references/dependencies.md).

Install the locked Python dependencies in an isolated environment:

**macOS / Linux**
```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements-docx.lock
.venv/bin/python scripts/app.py
```

**Windows PowerShell**
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-docx.lock
.\.venv\Scripts\python.exe scripts/app.py
```

Alternatively, double-click `Start-Video-Transcription.command` on macOS or `Start-Video-Transcription.bat` on Windows. The launchers ask before creating a virtual environment or installing Python dependencies. They do not install Python or FFmpeg automatically.

## Use the local interface

1. **Choose media.** Use the folder button or enter a path. Selection alone does not upload, recognize, or charge anything. Keep the suggested work folder outside the media folder.
2. **Prepare and review.** Check the actual file count, duration, estimated price, and destination. The default export name is `Transcription-Export`. If it already exists, explicitly continue its original batch or choose a new numbered export; existing files are not silently overwritten.
3. **Authorize this batch.** Set a total spending limit and approve the audio upload. Enter the API key only in the masked local field, never in chat. Cost reservations include possible charges from uncertain attempts; they are not a live provider bill or account balance.
4. **Run and recover.** The same operation can submit and collect results. A known task ID is queried rather than resubmitted. Transient failures are retried within bounded limits; unresolved items retain their records instead of erasing progress.
5. **Review outputs.** Open the viewer and documents. Check timestamps, names, speaker labels, and representative audio. “No recognized words” is a completed provider outcome, not proof that the recording contains no speech.

The service address is an advanced setting. A batch is bound to its original provider endpoint; do not switch regions or addresses to recover an uncertain request.

## Credentials and costs

API keys stay in the running process, not configuration files, command-line arguments, browser storage, logs, exports, or Git. Keys are released when the operation ends; a new operation or restarted process may require re-entry. System-keychain persistence is not implemented. Do not share the local page link or expose it through a public tunnel.

The user chooses the budget. Confirm current official pricing before running; free credits and billing rounding must not be assumed. Prior possible charges remain reserved until reconciled. Increasing a limit requires explicit confirmation and does not discard earlier costs.

If a submission response is lost, the provider may still have created a task. Exactly-once submission cannot be guaranteed without provider idempotency. Preserve that attempt. Reconcile it when possible, or explicitly authorize a bounded new attempt with possible duplicate charges included in the limit. The UI requires a duplicate-charge risk confirmation and a limit of 0–3 extra uncertain attempts; the count is retained across restarts. Without that confirmation, uncertain items remain isolated. Do not repeatedly click or delete state to force a retry. A failed query and a failed submission are different operations.

## AI-agent use

This skill is **explicit-only**. Install a host-specific copy, then invoke it by name. For example:

> Use batch-video-transcription on this video folder. Prepare the batch and show the scope and estimated cost before uploading.

The agent follows [SKILL.md](SKILL.md), checks dependencies and inputs, and opens the local interface for private key entry. It must not inspect the key field, screenshots containing credentials, network requests, or process memory.

Generate a host-specific installation folder from this single source:

```sh
python scripts/package_skill.py --host codex --output /path/to/new/codex/batch-video-transcription
python scripts/package_skill.py --host claude --output /path/to/new/claude/batch-video-transcription
```

Use a new destination outside this source tree. Packaging copies only an explicit file list; it does not install or publish anything.

- **Codex:** `agents/openai.yaml` sets `policy.allow_implicit_invocation: false`. Invoke `$batch-video-transcription`.
- **Claude Code:** the generated `SKILL.md` adds `disable-model-invocation: true`. Invoke `/batch-video-transcription`.
- **Other hosts:** configure and verify their equivalent explicit-only policy. A sentence in a description cannot enforce every host's behavior.

See [host packaging](references/host-packaging.md) for installation locations and compatibility boundaries. Metadata generation is tested; actual Claude runtime invocation is not verified.

## Exports and portability

The viewer uses relative links to original videos and individual Word files. Move the **entire media folder**, preserving its export subfolder and internal structure. Moving just the HTML, renaming videos, or moving only part of the tree breaks those relationships. Playback also depends on browser codec support; videos are not silently transcoded.

Generate a combined Word document from saved batch results:

```sh
python scripts/merge_export.py --work /path/to/batch-work
```

It sorts by source-relative path, preserves recognized wording, timestamps and per-video speaker labels, includes normal no-word outcomes, and lists any sources not yet exported. It makes no network requests. A new versioned `Transcript-Summary.docx` and provenance receipt are created without overwriting an existing summary. Speaker IDs are local to each video, not identities matched across the collection.

Read-only media folders require an explicitly chosen fresh writable export destination. External exports and Windows cross-drive file URLs are not guaranteed to remain portable. Viewing a moved package does not imply that its original processing state can safely be rebound to a different disk.

## Development and verification

```sh
python scripts/check_tests.py
```

Tests use synthetic media and mocked service responses, without real API charges. macOS has been used for local execution; Windows coverage is limited to path/platform logic and simulated tests. Windows installation, native dialogs, cancellation, and video playback still need real-machine verification. Browser playback and pagination need checks on the target environment. A passing test suite is not a guarantee of transcription accuracy or network availability.

Provider extension guidance is in [references/providers.md](references/providers.md). Submit focused tests with changes to recovery, budgets, credentials, or export identity. Do not include media, transcripts, keys, signed URLs, runtime batches, environments, or local logs in contributions.

## License

[MIT](LICENSE). This license covers this repository's code, not third-party runtimes, model services, or user media. Python, FFmpeg builds, codecs, and service usage have their own terms.
