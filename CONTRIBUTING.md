# Contributing

Use a focused branch and describe the resulting behavior and validation in your
pull request. Do not commit models, chat histories, runtime binaries, signing
keys, private paths, access tokens or generated build directories.

Preserve the weight-streaming invariant: load one decoder group's tensors,
compute, release references, then proceed. Add numerical reference tests when
changing inference. Test cancellation and failure paths when changing lifecycle
or downloads. Tests should cover behavior, not simply repeat implementation.

See BUILDING.md for dependencies and commands. The workflow tests Python behavior
on Linux and compiles/packages on Windows and Intel macOS. A green host workflow
still does not substitute for testing the Ventura minimum version and physical
Windows devices. Report exact OS, CPU, model revision, context and memory budget
when filing compatibility bugs. Avoid claiming unmeasured large-model speeds.
