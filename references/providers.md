# Provider extension contract

Only Alibaba Cloud Beijing Fun-ASR is implemented. `scripts/provider_contract.py` describes an extension boundary; it is not a dynamic plugin loader. Changing a Base URL does not add provider support.

A future adapter must explicitly identify provider, version, region, supported audio formats and pricing units. Bind these to each batch and attempt. Keep the common scheduler responsible for permission, total budget, single-writer coordination and source integrity.

- Upload only the authorized audio to approved service origins. Never leak credentials to redirected or result-download hosts.
- Before submit, persist an attempt intent and its cost reservation. Return a stable task ID where possible. A lost POST response is uncertain, not proof of failure.
- Poll only known IDs without implicit submission. Normalize timestamps in seconds, recognized wording and optional speaker labels. Preserve service-confirmed no-word outcomes separately from actual service errors.
- Expose bounded retry semantics and any provider idempotency support. Without idempotency, a new attempt after uncertainty needs explicit acceptance of possible duplicate charges and a new reservation. Do not advertise exactly-once delivery.
- Do not store credentials, signed URLs or upload policies in transcripts or receipts. Do not modify original videos or raise budgets.
- Test partial failures, rate limiting, interruption/restart, empty results, source changes and attempt recovery. Enable a provider only after an authorized live sample, and document unverified behavior.
