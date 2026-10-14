# Delivery verification — 2026-10-14

This branch transports the existing, validated image; it does not rebuild it.

- GitHub Releases API read checks (`gh api repos/goodstas/PyValidationAgent`) returned `Forbidden` in the build environment. Git transport remained available.
- Split `/workspace/artifacts/code-review-agent-v1.0-linux-amd64.tar.gz` into 13 chunks, at most 40 MiB each, using Python binary file I/O.
- Read back every saved chunk, verifying its byte size and SHA-256 against `manifest.json`; concatenated hash and total length match the original archive: 505,338,001 bytes, SHA-256 `3c71235cebca78e8469c1b77b11a53df412469c1338897cc414c6b441fc73490`.
- The PowerShell restore script uses binary streams and verifies individual and final hashes. Windows/PowerShell execution was not available here.
- Original image validation is recorded in `BUILD_INFO.json` and the application's `docs/compatibility.md` at commit `6bb8d4683ce6b8858c614f1848869c44f1267665`.
