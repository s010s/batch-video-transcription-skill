---
name: batch-video-transcription
description: Extract full-timeline audio from video batches and produce timestamped Chinese transcripts, speaker segments, Word documents, and local HTML search. Use only when explicitly invoked as batch-video-transcription.
---

# Batch Video Transcription

Use only after explicit invocation. Alibaba Cloud Beijing Fun-ASR is the only implemented recognition provider. Invocation does not authorize software installation, audio upload, spending, or public release.

## Workflow

1. Establish the exact media scope and independent work folder. Preserve original videos. Check stable downloads, audio tracks, free space, Python 3.10+, FFmpeg and ffprobe. Read [dependencies](references/dependencies.md) only if setup is needed; reuse a compatible environment and obtain permission before installation.
2. Prefer the local interface (`python scripts/app.py`) so the user can select a folder and review it. For an existing batch use `--work '<work>'`; do not initialize it again. Preparation is local, and a selected subset must never expand silently. The default export folder is `<source>/Transcription-Export`; resolve conflicts without deleting or overwriting prior output. See [execution](references/execution.md) for CLI preparation and exact scope options.
3. Report the actual count, duration, destination and current-price estimate. Obtain permission for this batch's upload and total limit. Account for prior possible charges automatically; do not ask the user to calculate the residual budget. Reserved cost is not actual billing or available account credit.
4. Have the user enter the key privately in the local masked field and confirm the batch. Never read the key through chat, screenshots, DOM, requests, files or process memory. Keep the current operation running rather than replacing it to fix an unrelated item. Observe only key-free task state and outputs.
5. Verify delivered files against each source, including timestamps and text. Treat provider-confirmed no-word results as normal completed outputs with a brief factual note, not as proof of silence. Distinguish unresolved submissions, genuine failures, and unfinished downloads from completion. Generate a combined Word summary when requested using `python scripts/merge_export.py --work '<work>'`. Preserve wording and per-video speaker IDs. Report any unperformed listening, playback or visual checks.

## Recovery

Maintain one writer per batch and retain task IDs, attempt history and cost reservations. Query known IDs; do not resubmit them to recover downloads. Use bounded retry/backoff for transient queries and isolate unresolved items so unrelated work can continue. Do not clear locks or erase fault history to force progress.

A lost submission response may still have incurred a charge. Preserve the uncertain attempt. Reconcile it where possible, or obtain explicit acceptance of possible duplicate charges before a limited new attempt, with both reservations inside the authorized total. Do not claim exactly-once delivery. A larger budget is a separate user decision.

Respect user pause before offering a recovery action. In-flight requests cannot be revoked; save returned IDs at safe boundaries. Source/disk changes, credential errors and quota failures need diagnosis, not blind retries. Read [operations](references/operations.md) for state and credential boundaries and [execution](references/execution.md) for recovery commands.

## Scope and maintenance

Keep the interface local-only and do not share its session link. Keys are not persisted across process restarts. Do not advertise system-keychain storage or untested host/platform behavior as implemented.

Load [providers](references/providers.md) only when adding a provider, and [host packaging](references/host-packaging.md) only when installing or distributing a host-specific copy. After code changes run `python scripts/check_tests.py`; mocked tests do not prove live recognition. Package only source, documentation and tests, never runtime data or credentials.
