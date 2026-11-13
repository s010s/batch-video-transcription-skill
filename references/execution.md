# Execution reference

## Local preparation

Use the user's chosen computer and source. Work/cache storage must be outside the media tree, with enough free space for extracted audio and results. Do not modify the videos. Reuse compatible dependencies; see [dependencies](dependencies.md) only when setup is needed.

From the toolkit directory:

```sh
python scripts/toolkit.py init --root '/path/to/videos' --work '/path/to/new-batch'
python scripts/toolkit.py prepare --work '/path/to/new-batch'
python scripts/toolkit.py status --work '/path/to/new-batch'
```

For a subset, add `--include-file 'source-relative/video.mp4'` once per file to `init`. The list is persisted against the original source. Do not broaden it silently or copy media to disguise the source. Reuse a matching batch rather than initialize again. `prepare` validates inputs and extracts 16 kHz mono PCM WAV, preserving the complete timeline; it makes no cloud calls. Distinguish unstable downloads, corrupt files and missing audio.

New exports reserve `<source>/Transcription-Export`; explicitly resolve name conflicts without overwriting previous results. A fresh writable external destination can be supplied with `--export-dir`, but external and cross-drive links are not guaranteed portable.

## Recognition and permission

Report the actual scope, duration, service destination and current-price estimate. Confirm audio upload and a maximum total spend. The current interface uses the Beijing Fun-ASR price CNY 0.00022/second; verify [official pricing](https://help.aliyun.com/zh/model-studio/model-pricing) before submitting. Do not infer free credits or report cost reservations as actual billing.

Prefer the local page:

```sh
python scripts/app.py --work '/path/to/batch'
```

The default Beijing-compatible origin is `https://dashscope.aliyuncs.com`; a Beijing workspace origin can be configured in advanced settings. The batch must retain its original origin. Do not switch origins or providers to retry an uncertain task. An address documented by the provider or covered by mocks is not proof of successful live authentication.

The user enters a key in the masked local field. Do not collect it through chat, command arguments, screenshots, DOM, request capture or memory inspection. An operation can submit and collect using that in-memory credential; keys are not retained across restarts. No system-keychain persistence is implemented.

For users explicitly preferring a terminal, consult current command help and use masked input:

```sh
python scripts/toolkit.py authorize --work '/path/to/batch' \
  --budget-yuan '<approved-limit>' --price-yuan-per-second '<verified-price>' \
  --upload-authorized --paid-authorized
python scripts/toolkit.py submit --work '/path/to/batch'
python scripts/toolkit.py collect --work '/path/to/batch' --wait
python scripts/toolkit.py viewer --work '/path/to/batch'
```

Terminal commands are separate operations and may each require private key entry. Do not reuse a sample's spending permission for an unapproved larger scope.

## Pause and recovery

```sh
python scripts/toolkit.py pause --work '/path/to/batch'
```

Pause requests take effect at safe boundaries. They cannot cancel an already-issued request; record returned IDs first. Preserve the authoritative batch state and historical reservations. Never delete an operation lock without verifying no writer remains.

Known IDs require only queries and downloads. Retry transient GET failures with bounded delay; a deferred item is not completed. Isolate item-level failures so unrelated work can proceed. Credential/quota errors or disk/source changes require diagnosis rather than blind retries.

An uncertain POST may have created a task. Retain that attempt and charge reservation. Reconcile candidates only with reliable source evidence, not just similar times or durations. A user may explicitly accept duplicate-charge risk for a limited new attempt; keep both attempts and budget reservations. Do not turn that into unlimited retries or reset the cost history.

See [operations](operations.md) for credential, state and portability boundaries.

## Deliverables and verification

The batch-recorded export directory contains:

- `转写结果明细`: per-video Word documents organized by source-relative path.
- `转写结果/视频文字稿.html`: local playback, timestamp navigation and cross-video search.
- Sanitized recognition details, normalized JSON, sentence transcripts, subtitles and provenance.

For a combined Word summary:

```sh
python scripts/merge_export.py --work '/path/to/batch'
```

The merger reads local normalized results, verifies source and turn correspondence, preserves text and time ranges, and writes a new versioned summary plus result-identity receipt. It does not upload or invoke recognition. Speaker IDs remain per-video. Provider-confirmed no-word outcomes receive a factual note and count as completed outputs; other unfinished sources remain listed. Do not claim silence or invent text.

Check source coverage, timestamp bounds, exact wording, version identity and output existence. Test viewer links, search, playback and seeking on the target browser; codec support varies. Listen to representative clips when possible. Keep human edits separate and disclose unperformed checks. A generated file is not proof of recognition accuracy.
