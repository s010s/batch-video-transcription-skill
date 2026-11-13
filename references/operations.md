# Operations and recovery boundaries

## State and recovery

Keep the source media and work directory independent. Each batch has one writer; acquire its operation lock before reading state for a mutation. A user pause takes precedence over recovery actions. A pause cannot revoke an already-issued request: persist returned IDs before stopping at a safe boundary.

Known task IDs are queried, not resubmitted. Transient query or upload failures need bounded backoff and visible per-item status; an unresolved item must not erase progress or prevent unrelated safe work. Distinguish a deferred query from a completed result. Authentication, quota, changed disks, and invalid source fingerprints need intervention rather than repeated requests.

For an ambiguous submission, keep the original attempt and its reserved cost. Use provider evidence to reconcile where possible. Time and duration can filter candidates but cannot prove ownership. An explicitly approved new attempt may duplicate charges: limit attempts, retain the history, and reserve every potential charge inside the total limit. The UI limits extra uncertain attempts to 0–3 and persists the count across restarts. Do not force recovery by deleting state or locks.

A provider-confirmed no-word response is a normal completed document outcome. It is not a claim that no one spoke. Genuine service errors, missing audio, pending requests and unknown submissions remain distinct.

## Budget and credential lifetime

A provider account/key does not grant permission to spend. The recorded total limit and prior potential charges are restored from batch state on restart. An optional externally imposed cap can further restrict the limit. Reserved totals are estimates, not bills. Increasing the limit does not clear faults or release unknown reservations.

Keys must not enter chat, arguments, configuration, URLs, logs, browser storage, exports or repositories. Use a masked local field; agents must not inspect it. Current key handling is process-memory only, released after an operation; another operation or restart may require re-entry. Clearing Python references is not a guarantee of forensic memory erasure. System-keychain persistence is not implemented.

The page listens on loopback and checks Host, Origin and a random session token. The non-API session token is retained in a URL fragment for refresh; browser history can retain that link. Do not share it or expose the interface with a public tunnel. It expires when the server exits.

## Output integrity

Source fingerprints, disk identity and normalized-result identity prevent unintended reuse. Keep old attempts and edited documents. Combined summaries are new versioned outputs, not replacements. Keep source-relative ordering and per-video speaker IDs; do not merge identities across recordings.

Default exports are inside the source folder, named `Transcription-Export`. Explicitly handle conflicts without overwriting. Generated directories are marked and excluded from rescans. Preserve the entire media/export tree to keep relative links valid when moving it. Viewing moved files is different from safely rebinding a running batch to a new disk. Cache validation is not a long-term backup.

## Platform checks

Windows support is implemented but not real-machine end-to-end certified. Verify native dialogs, installation, process cancellation, Chinese paths, cross-drive links and playback on the target platform. Browser codec support may block playback even when links and text are valid. Synthetic/mock tests cannot certify live provider availability, transcription quality, or GUI rendering.

## Persisted receipts

State writes use a pending-state journal, revision and dual-copy readback. This is recovery support, not an atomic transaction across files. Receipt recovery must keep the batch paused and preserve all costs. Do not describe a repaired copy as successful recognition. Existing Word/HTML exports require matching version and hashes before reuse; a conflicting existing output is preserved for resolution, never silently replaced.


Returned task IDs are also saved in an independent, per-attempt `response-receipts` inbox. Receipt repair merges late IDs without losing the original attempt or fee reservations. `repair-receipts` leaves the batch paused and retains the previous fault reason; it uses `user_pause` only when there was no prior reason. Resolve the remaining fault before resuming.

CLI `authorize --budget-yuan` sets the total batch budget, deducting persisted prior possible charges. An external approved cap cannot be bypassed by entering a higher budget. Ambiguous resubmission requires `--accept-duplicate-cost` with `--max-unknown-retries` from 0 to 3 (default 0). These flags do not release old reservations.

CLI `merge` creates a local combined Word document. It refuses pending receipt recovery or a changed normalized-result/export version. It also verifies the existing individual Word hash. Edited transcripts or documents are preserved for explicit review rather than silently incorporated as verified provider output.
