# Security

RamPilot is a development-stage local model runner. Use model files from trusted
sources. The engines read SafeTensors and local tokenizer/config JSON without
executing remote model Python code. Unsupported formats are rejected.

Windows serves an internal API on authenticated 127.0.0.1 only, with a random
per-process token. The token is not written into exported diagnostics. Mac does
not start a network service. Neither app exposes tools, shell access or agents
to model output. Treat generated text as untrusted and verify important answers.

Model download integrity is pinned by revision and SHA-256. Release/runtime inputs
have recorded checksums. The desktop builds are not code-signed or notarized.
Do not disable your operating system's security globally to run them.

Diagnostics are deliberately limited, but error logs can contain local paths.
Never attach private conversations, credentials or unreviewed logs to a public
issue. For a suspected vulnerability, use GitHub's private vulnerability reporting
when enabled, or contact a maintainer privately. Do not post exploit details or
sensitive data in a public issue before coordinating a fix.
