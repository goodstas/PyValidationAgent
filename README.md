# Download code-review-agent:v1.0

This branch delivers the **already-built Linux/amd64 image**, including the application and DemoShop.
No rebuild is required. It is the exact image built from application commit
[`6bb8d46`](https://github.com/goodstas/PyValidationAgent/commit/6bb8d4683ce6b8858c614f1848869c44f1267665).

The 482 MiB compressed image is split into 13 files to fit GitHub's per-file limit. This delivery branch
is separate from `claude/focused-mayer-w705q4`; do not merge it into the application branch.
Access follows this repository's visibility and permissions.

## Download

Click **Code → Download ZIP** on this branch, then extract the ZIP. Allow about 1.5 GB of temporary
disk space for the ZIP, extracted parts, and assembled archive, plus space for Podman's loaded image.

Alternatively, clone just this branch:

```powershell
git clone --depth 1 --single-branch --branch artifacts/code-review-agent-v1.0 https://github.com/goodstas/PyValidationAgent.git code-review-agent-download
cd code-review-agent-download
```

## Windows: assemble and load

Open PowerShell in the extracted/cloned folder and run:

```powershell
.\Restore-Image.ps1
podman load -i .\code-review-agent-v1.0-linux-amd64.tar.gz
```

The script checks each chunk, joins them in manifest order, and verifies the final SHA-256.
If your Windows policy blocks downloaded scripts, open `Restore-Image.ps1` in a text editor and review it.
You can run its contents in PowerShell after replacing `$Root = $PSScriptRoot` with `$Root = (Get-Location).Path`.
The script performs only local file reads/writes and checksum checks; it does not authenticate or contact a service.

Expected archive SHA-256:

```text
3c71235cebca78e8469c1b77b11a53df412469c1338897cc414c6b441fc73490
```

## Linux: assemble and load

From the downloaded folder:

```bash
cat parts/image.part-* > code-review-agent-v1.0-linux-amd64.tar.gz
sha256sum -c SHA256SUMS
docker load -i code-review-agent-v1.0-linux-amd64.tar.gz
```

## Authenticate and run

Follow [RUN_INSTRUCTIONS.md](RUN_INSTRUCTIONS.md) for Windows/Podman ADC, runtime `GEMINI_MODEL`,
Vertex AI, report persistence, and deployment to project `hack-team-7-0ecb`.
The archive includes no Google credentials. Real Gemini access requires your ADC identity and an available model.
See [BUILD_INFO.json](BUILD_INFO.json) for image/source identities and validation results.

The original image passed 67 Python tests, 15 analyzer tests, offline CLI/MCP scans, report persistence checks,
and export/reload verification. Offline scans correctly reported `partial` without model configuration.
The Windows PowerShell assembly script is supplied for Windows; its execution was not tested in the Linux build environment.
