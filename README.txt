RamPilot 2.1.0 - Local CPU layer streaming

WINDOWS: Run RamPilot-Setup-2.1.0.exe on Windows 10/11 x64. Requires .NET
Framework 4.8. Setup includes Python/PyTorch CPU and the Microsoft VC runtime
installer when needed. No separate Python, GPU or API account is needed.

INTEL MAC VENTURA: Extract the Intel Mac ZIP and move RamPilot.app into
Applications. Includes Python, Tk and NumPy. No separate Python is needed.
These development builds are unsigned. The Mac app is not Apple-notarized.
Check release SHA-256 values and review the source before choosing to trust it.

FIRST RUN: Open Models. Start with Qwen 2.5 0.5B. Download / verify / resume,
then Load the model. Type a message in Chat. Return sends, Shift+Return adds
a line. Stop interrupts. The 0.5B model needs about 0.93 GiB disk space.

Windows supports standard dense Qwen2/Qwen2.5 and Llama SafeTensors; Mac
supports standard Qwen2/Qwen2.5. GGUF, quantized SafeTensors, MoE, custom
architectures, audio/image models and training are not supported.

Weights are read and released one decoder block at a time with ordinary file
reads. Embeddings and output projections use row/chunk reads. Runtime,
tokenizer, active weights, temporary workspace and KV cache still need RAM.
A block and its workspace must fit. Budget checks are not OS hard limits.
OS/native allocators can retain freed memory. Mac RAM figures are peak RSS.
Every generated token rereads weights. An SSD helps; large models can be very
slow. No arbitrary large-model or usable 70B performance guarantee is made.

NEW IN 2.1: Saved conversations, persistent generation settings, temperature
control, diagnostics export, richer performance measurements, repaired model
downloads with damaged-file preservation, and automated native build checks.

Models download from Hugging Face. Chat inference stays local. No telemetry,
cloud inference, shell tools or agents. Windows uses authenticated loopback
HTTP internally; Mac calls its engine directly. Model files have their own
licenses. 0.5B/1.5B use Apache-2.0; the 3B catalog model has different terms.

DATA: Windows %LOCALAPPDATA%\RamPilot; Mac ~/Library/Application Support/RamPilot2.
Chats/settings are plain JSON. Completed saved conversations remain available
when you start New chat. Disabling saving stops future chat writes; it does
not erase old archives. Removing app binaries preserves separate data folders.
Mac logs: ~/Library/Logs/RamPilot2.log. Diagnostics omit private chat and paths.

See README.md, PLATFORMS.md and TEST-REPORT.md in the source repository for
usage details, exact completed checks and remaining device validation.
