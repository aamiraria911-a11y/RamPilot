# Install and use RamPilot 2.1

## Windows 10/11 x64

Download and run `RamPilot-Setup-2.1.0.exe` from Releases. Setup installs per user,
adds Start menu/desktop shortcuts and includes an uninstaller. You need .NET
Framework 4.8. Setup includes the Microsoft Visual C++ runtime installer if needed;
that prerequisite may request administrator permission. The app itself does not
need administrator rights. This unsigned development build may show a publisher
warning. Check the release SHA256SUMS.txt against your download before installing.

Open Models, select Qwen 2.5 0.5B, choose Download / verify, then Load selected
model. Use Chat to send messages. Settings apply when you reload. Saved chats
opens previous conversations, and New chat starts a fresh conversation while
keeping completed archives when saving is enabled.

## Intel macOS Ventura 13+

Download and extract `RamPilot-Mac-Ventura-Intel-2.1.0.zip`, then move RamPilot.app
to Applications. The app targets Intel x86_64 Macs. It is unsigned and has not
been Apple-notarized. If macOS blocks opening it, inspect the app's source and
checksum, then use the app-specific Open/Privacy & Security option if you choose
to trust this development build. Do not disable Gatekeeper system-wide.

In Models, start with Qwen 2.5 0.5B. Download / verify / resume checks every file
before marking it ready. Load model to start. Import folder accepts a complete
Qwen2/Qwen2.5 SafeTensors folder. Existing Ollama/GGUF files are not compatible.

Chat has a searchable saved-conversation sidebar, streaming replies, Stop, copy
last reply and export. Settings persist context, RAM budget, reply length,
temperature, system instructions and whether future conversations are saved.
Context/RAM changes need a reload; generation settings apply to the next reply.

Start with 512 context tokens and a 2048 MB planning budget on Mac. The budget
checks anticipated allocations, not an OS-enforced ceiling. Peak RAM figures can
stay high after memory has been released. Larger models/context may be slow or
fail the allocation checks. Every output token rereads the model weights.

## Downloads and repair

All catalog files are pinned by revision and SHA-256. Download resumes `.part`
files, verifies existing completed files and writes a ready marker only when all
checks pass. If a completed managed file is damaged, repair preserves it with a
`.corrupt-*` suffix, then downloads a replacement. These preserved files consume
disk space; you may remove them manually when no longer needed. Import never
moves or repairs files in your own external folders.

Internet is needed for downloading models only. The smallest model requires
about 0.93 GiB of storage. Use an SSD. The 1.5B and 3B options need more disk space
and substantially more processing time. No usable large-model speed is promised.

## Data, diagnostics and troubleshooting

| Item | Windows | Mac |
| --- | --- | --- |
| Local data | `%LOCALAPPDATA%\RamPilot` | `~/Library/Application Support/RamPilot2` |
| Saved conversations | `Conversations` inside local data | `Conversations` inside local data |
| App log | Engine log button | `~/Library/Logs/RamPilot2.log` |
| Diagnostics export | Memory & settings | Sidebar |

Diagnostics omit chat contents, usernames, model paths and session keys. Review
a diagnostic file before attaching it to an issue. Logs can contain paths or
error context, so review those separately. There is no automatic upload.

If the engine fails to load: choose the 0.5B model, reduce context, verify files,
and check that the model format/architecture is supported. If memory checks fail,
close other apps, lower context, choose a smaller model, or increase the budget
only if your computer has available RAM. A larger budget does not create memory.

Stop keeps the prompt for retry. Completed turns are saved; partial/stopped turns
are not committed as finished conversation history. New chat preserves saved
archives. Turning saving off does not erase old archives. Uninstalling the app
preserves the separate data folder. See TEST-REPORT.md for tested behavior and
remaining native-device validation.
