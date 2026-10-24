# Changes

## 2.1.0 (development release)

- Rebuilt the Mac UI with Chat, Models and Settings tabs and searchable saved conversations.
- Added Windows saved conversations, temperature control and diagnostics export.
- Added Mac persistent generation preferences, copy reply and private diagnostics export.
- Added measured token counts, prompt-inclusive reply speed, first-token latency and disk-read metrics.
- Strengthened download range/TLS/integrity checks and repair with damaged-file preservation.
- Added atomic local state, preference bounds and history recovery tests.
- Added checksum-verified Mac runtime bootstrapping and immutable Windows runtime locks.
- Added native Windows/Intel Mac build workflows, packaged-engine smoke checks and release checksums.

## 2.0.0

Introduced explicit CPU layer streaming with ordinary file reads, one live decoder
weight group, row/chunked embedding/output handling, bounded context and cancellable
chat. Windows supports dense Qwen2/Llama; the lightweight Mac engine supports Qwen2.
