# RamPilot 2.1 validation

## Executed on the Linux build host

- 29 Python tests passed, including three Tk UI tests under Xvfb. Coverage:
  Qwen2/Llama reference logits, cached decoding, chunked prefill, one live decoder
  weight group, release checks, budget/context rejection, cancellation, tokenizer
  parity, malformed weights, state bounds, corrupt JSON recovery, stable saved
  conversations, atomic writes, download resume/range validation, SHA-256 failure,
  damaged-file preservation, re-verification, interrupted download recovery, UI
  control freezing, retry behavior and UI-thread settings capture.
- C# desktop conversation/downloader checks passed under Mono: Unicode session
  round-trip, stable identity, malformed archive handling, partial-turn rejection,
  exact download resume, integrity verification, ready marker creation/removal
  and damaged-file repair. Production uses .NET Framework on Windows.
- Real pinned Qwen2.5-0.5B-Instruct SafeTensors weights generated `OK` using the
  updated NumPy service. The conversation was saved, cleared and reopened.
  Instrumentation observed one live decoder weight group maximum, zero after
  completion, 72 released groups, and 59,649,536 bytes for the largest FP32 block.
  This particular run used about 114 MB final process RSS and took about 2.61 s
  including its 30-token prompt and one output token. It read about 2.69 GB from
  model file ranges. These are Linux-host measurements, not Mac/Windows benchmarks
  or evidence of larger-model performance. OS caching affects observed speed.
- Windows Chat, Models and Settings and all three Mac tabs were rendered and
  visually inspected. The Windows settings page scrolls when it does not fit.
  These renders used Linux Mono/Tk, not the platforms' native window systems.
- Source compilation, the native NumPy smoke fixture, and Python syntax checks
  passed. The real-model C# client/server integration also passed: model load,
  templates/token counts, streamed generation, old-turn trimming, oversized
  prompt rejection, cancellation, one-group metrics, unload and cancelled startup.

## Packaging and native validation

Windows setup and the Intel Mac app are rebuilt for 2.1. Runtime inputs are pinned
with publisher SHA-256 values. Package integrity, architecture, symlink/launcher
permissions, latest source inclusion and release hashes are checked during local
packaging. SHA256SUMS.txt identifies the final downloadable files.

The native hosted [workflow run](https://github.com/aamiraria911-a11y/RamPilot/actions/runs/40046458866)
passed all three build/check jobs:

- Ubuntu: all 29 Python tests and the standalone NumPy smoke fixture.
- Windows Server 2022: clean .NET compilation with zero warnings/errors, complete
  installer assembly, all 12 C# desktop checks, all eight packaged PyTorch engine
  tests, silent setup into a temporary folder and installed app startup smoke.
- Intel macOS 15: checksum-verified runtime assembly, ZIP packaging, native Tk
  creation, NumPy matrix/inference/cache/layer-release smoke and local-state tests.

The initial Windows attempts exposed NSIS path-specification issues; the final
build uses explicit project-root paths and native Windows path separators.
No physical device or macOS Ventura execution has been performed by this task.
The release workflow builds the same tagged source and attaches successful native
packages plus SHA256SUMS.txt; inspect that run for release-upload completion.

Not established by these checks: performance on arbitrary models, actual
low-memory device behavior, power/thermal behavior, UAC behavior on all machines,
Ventura minimum-version compatibility or production signing/notarization. These
remain development builds until verified on the relevant hardware and OS.

Budget checks are advisory allocation planning, not hard OS memory ceilings.
Runtime/tokenizer/activations/KV state still use RAM, and native allocators or OS
caches may retain released memory. Large models reread weights for every token
and can be impractically slow. No usable 70B performance claim is made.

