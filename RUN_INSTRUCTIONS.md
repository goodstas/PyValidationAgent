# Run the bundled image with Gemini on Vertex AI

Image: `code-review-agent:v1.0` (Linux **amd64**, Python 3.12, .NET SDK 10.0.103).
It contains the application, compiled analyzers, a read-only DemoShop at `/workspace/repo`,
ground truth at `/app/demo/ground-truth.json`, and smoke/probe clients at `/app/scripts/`.
No Google credentials, `.env`, prior reports, or model responses are included.

The image is built outside GCP. Loading, pushing, or running it does not rebuild it.
The model is always selected at runtime. `gemini-3.8-flash` below is the requested model ID,
**not a claim that Google has made it available in your project/location**. The probe must succeed
before treating a scan as a live Gemini validation. No silent model/provider fallback is used.

There are three separate authentication concerns:

* A downloaded archive needs no registry login.
* Vertex AI needs Google Application Default Credentials (ADC) and IAM permission.
* This runbook explicitly enables anonymous MCP/REST access. `SERVICE_TOKEN`, if set, still requires bearer authentication.

## 1. Windows + Podman: load the downloaded image

Install Podman Desktop/CLI and Google Cloud CLI. Run PowerShell. Initialize a Linux Podman machine
once if needed (`podman machine init --cpus 4 --memory 8192 --disk-size 40`), then start it:

```powershell
podman machine start
# Compare this value with the entry in SHA256SUMS supplied beside the archive.
Get-FileHash .\code-review-agent-v1.0-linux-amd64.tar.gz -Algorithm SHA256
podman load -i .\code-review-agent-v1.0-linux-amd64.tar.gz
podman image inspect code-review-agent:v1.0 --format '{{.Os}}/{{.Architecture}}'
```

This requires an x86-64 Windows host (or explicitly configured amd64 emulation on ARM).
If the machine is already running, continue without restarting it.

## 2. Authenticate to Vertex AI on Windows

Set the project and the model/location you intend to verify:

```powershell
$Project = 'hack-team-7-0ecb'
$Location = 'global'  # Replace with the Vertex location supporting your model; independent of VM region.
$Model = 'gemini-3.8-flash'
gcloud auth login
gcloud config set project $Project
```

Choose **one** ADC method. For your Google user:

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project $Project
```

Or, to use a service account without downloading a service-account key:

```powershell
$ServiceAccount = 'YOUR_SERVICE_ACCOUNT@hack-team-7-0ecb.iam.gserviceaccount.com'
gcloud auth application-default login --impersonate-service-account=$ServiceAccount
gcloud auth application-default set-quota-project $Project
```

The user needs permission to impersonate the service account (`roles/iam.serviceAccountTokenCreator` on that
account). The calling identity/service account needs `roles/aiplatform.user` in the workload project.
Setting/using a quota project requires `serviceusage.services.use`, commonly via `roles/serviceusage.serviceUsageConsumer`.
An administrator must enable `aiplatform.googleapis.com` if it is not already enabled.
`gcloud auth login` alone does **not** create application ADC.

Import ADC into a Podman secret, without printing its contents. This avoids Windows bind-mount UID/permission issues:

```powershell
$ConfigDir = (gcloud info --format='value(config.paths.global_config_dir)').Trim()
$Adc = Join-Path $ConfigDir 'application_default_credentials.json'
if (-not (Test-Path $Adc)) { throw "ADC file missing: complete application-default login first." }
podman secret create syc-google-adc $Adc
```

The secret belongs to your local Podman machine, not the image or GitHub. If you log in again or change identities,
stop/remove the application container, remove this secret (`podman secret rm syc-google-adc`), recreate it from
the updated ADC file, and recreate the container. Normal token refresh uses the mounted ADC automatically.

## 3. Start locally and preserve reports

Initialize a named data volume once. The small initialization container only sets its ownership:

```powershell
podman volume create syc-data
podman run --rm --user 0 --entrypoint sh -v syc-data:/data code-review-agent:v1.0 `
  -c 'chown 1654:1654 /data'

podman run -d --name code-review-agent --restart unless-stopped `
  -p 127.0.0.1:8000:8000 `
  -v syc-data:/data `
  --secret 'syc-google-adc,type=mount,target=/run/secrets/adc.json,uid=1654,gid=1654,mode=0400' `
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/adc.json `
  -e "GOOGLE_CLOUD_PROJECT=$Project" `
  -e "GOOGLE_CLOUD_LOCATION=$Location" `
  -e "GEMINI_MODEL=$Model" `
  -e GOOGLE_GENAI_USE_VERTEXAI=true `
  -e MODEL_PROVIDER=vertex `
  -e ALLOW_UNAUTHENTICATED_PUBLIC=true `
  code-review-agent:v1.0

Invoke-RestMethod http://127.0.0.1:8000/healthz
podman exec code-review-agent python /app/scripts/vertex_probe.py
podman exec code-review-agent python /app/scripts/smoke_client.py --via mcp --url http://127.0.0.1:8000
```

The explicit public-mode flag permits binding inside the container to `0.0.0.0`; the Windows port above is
published only on loopback. For your MCP client select **Streamable HTTP**, URL `http://127.0.0.1:8000/mcp`,
and no authentication. Tools are `scan_repository`, `get_scan_status`, and `get_scan_report`.
The bundled demo is selected server-side; clients do not provide repository paths.

`/healthz` confirms server startup, not Vertex access. The probe makes a real billable model request.
A successful scan must report `complete`; `partial` is a diagnostic result, not a successful Gemini review.
Missing configuration, permission errors, unavailable models and timeouts remain visible in the report.
The smoke client's exit code 0 means it retrieved a terminal report; inspect its printed scan status too.

Reports persist across `podman restart` and container replacement while the named volume is retained:

```powershell
podman logs code-review-agent
podman cp code-review-agent:/data/runs .\scan-reports
podman restart code-review-agent
```

Do not delete `syc-data` if you need the reports. Windows/Podman commands are supplied for execution on your
machine; the build environment validates the equivalent Linux Docker workflow, not Windows itself.

## 4. Push the already-built image to your GCP registry

No Cloud Build is used. Artifact Registry stores the image built/loaded locally.
Your pushing identity needs `roles/artifactregistry.writer` on the existing Docker repository.

For **Podman** on Windows (Docker's credential-helper configuration does not configure Podman):

```powershell
$Registry = 'me-west1-docker.pkg.dev'
$RemoteImage = "$Registry/hack-team-7-0ecb/hack-team-7-docker-repo/code-review-agent:v1.0"
gcloud auth print-access-token | podman login -u oauth2accesstoken --password-stdin $Registry
podman tag code-review-agent:v1.0 $RemoteImage
podman push $RemoteImage
```

For **Docker**, use the credential helper requested by your GCP team:

```bash
gcloud auth configure-docker me-west1-docker.pkg.dev
docker tag code-review-agent:v1.0 me-west1-docker.pkg.dev/hack-team-7-0ecb/hack-team-7-docker-repo/code-review-agent:v1.0
docker push me-west1-docker.pkg.dev/hack-team-7-0ecb/hack-team-7-docker-repo/code-review-agent:v1.0
```

The registry remains private unless your administrators explicitly change its IAM policy. Public anonymous
MCP does not require a public container registry. No workload or registry is created in `eng-network`.

## 5. Compute Engine: runtime identity and persistent disk

These are deployment commands for you/an authorized administrator, not actions performed during image creation.
Use Bash (Cloud Shell is fine for administration; it does not build the image). Reuse approved existing resources
if available. Replace the network with your team's approved VPC if `default` is unavailable.

```bash
PROJECT=hack-team-7-0ecb
REGION=me-west1
ZONE=me-west1-a
VM=code-review-agent
SA=code-review-agent-sa@$PROJECT.iam.gserviceaccount.com
NETWORK=default

gcloud services enable compute.googleapis.com aiplatform.googleapis.com artifactregistry.googleapis.com --project="$PROJECT"
gcloud iam service-accounts create code-review-agent-sa --project="$PROJECT" --display-name='Code Review Agent'
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/aiplatform.user
gcloud artifacts repositories add-iam-policy-binding hack-team-7-docker-repo \
  --project="$PROJECT" --location="$REGION" --member="serviceAccount:$SA" --role=roles/artifactregistry.reader

gcloud compute disks create syc-data --project="$PROJECT" --zone="$ZONE" --size=30GB --type=pd-balanced
gcloud compute instances create "$VM" --project="$PROJECT" --zone="$ZONE" \
  --machine-type=e2-standard-4 --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --service-account="$SA" --scopes=cloud-platform \
  --network="$NETWORK" --tags=code-review-agent \
  --disk=name=syc-data,device-name=syc-data,mode=rw,boot=no,auto-delete=no
gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE"
```

SSH/IAP access must follow the selected network's policy. Organization policies may restrict public IP addresses
or firewall creation; use your team's approved equivalent if so. The separate data disk is retained when the VM
is deleted. Back it up according to your team's policy; container restarts do not delete its contents.

On the VM, install Docker and mount **the newly created empty** data disk (format it only on first use):

```bash
sudo apt-get update
sudo apt-get install -y docker.io
sudo systemctl enable --now docker
DATA_DEVICE=/dev/disk/by-id/google-syc-data
if ! sudo blkid "$DATA_DEVICE" >/dev/null; then sudo mkfs.ext4 -m 0 "$DATA_DEVICE"; fi
sudo mkdir -p /mnt/disks/syc-data
DATA_UUID=$(sudo blkid -s UUID -o value "$DATA_DEVICE")
if ! grep -q "UUID=$DATA_UUID " /etc/fstab; then
  printf 'UUID=%s /mnt/disks/syc-data ext4 defaults 0 2\n' "$DATA_UUID" | sudo tee -a /etc/fstab
fi
sudo mount -a
sudo chown 1654:1654 /mnt/disks/syc-data
# Ensure Docker only starts after the persistent mount is available.
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nRequiresMountsFor=/mnt/disks/syc-data\n' | sudo tee /etc/systemd/system/docker.service.d/syc-data.conf
sudo systemctl daemon-reload

IMAGE=me-west1-docker.pkg.dev/hack-team-7-0ecb/hack-team-7-docker-repo/code-review-agent:v1.0
curl --fail --silent -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' \
  | sudo docker login -u oauth2accesstoken --password-stdin me-west1-docker.pkg.dev
sudo docker pull "$IMAGE"
```

This login obtains the VM service account's short-lived token; it does not create a service-account key.
At runtime the application automatically gets ADC from VM metadata. Do not set `GOOGLE_APPLICATION_CREDENTIALS`
to the Windows file path on the VM.

## 6. Public anonymous MCP over HTTPS

Reserve a stable external VM IP through your network team, and point a DNS name you control at it.
Set `MCP_HOST` to that DNS name below; HTTPS certificate issuance requires correct public DNS and inbound ports
80/443. A domain/IP and network access are deployment prerequisites, not baked into the image.

On the VM:

```bash
MCP_HOST=mcp.YOUR-DOMAIN.example  # replace with your real DNS name
VERTEX_LOCATION=global          # use the location verified for your model
GEMINI_MODEL=gemini-3.8-flash
IMAGE=me-west1-docker.pkg.dev/hack-team-7-0ecb/hack-team-7-docker-repo/code-review-agent:v1.0
sudo docker network create syc-net
sudo docker run -d --name code-review-agent --restart unless-stopped \
  --network syc-net -p 127.0.0.1:8000:8000 \
  --mount type=bind,src=/mnt/disks/syc-data,dst=/data \
  -e GOOGLE_CLOUD_PROJECT=hack-team-7-0ecb \
  -e GOOGLE_CLOUD_LOCATION="$VERTEX_LOCATION" -e GEMINI_MODEL="$GEMINI_MODEL" \
  -e GOOGLE_GENAI_USE_VERTEXAI=true -e MODEL_PROVIDER=vertex -e ALLOW_UNAUTHENTICATED_PUBLIC=true \
  -e MCP_ALLOWED_HOSTS="$MCP_HOST,$MCP_HOST:443" \
  "$IMAGE"
sudo docker exec code-review-agent python /app/scripts/vertex_probe.py
sudo docker exec code-review-agent python /app/scripts/smoke_client.py --via mcp --url http://127.0.0.1:8000

sudo mkdir -p /opt/syc
printf '%s {\n reverse_proxy code-review-agent:8000 {\n  flush_interval -1\n }\n}\n' "$MCP_HOST" \
  | sudo tee /opt/syc/Caddyfile
sudo docker run -d --name syc-https --restart unless-stopped --network syc-net \
  -p 80:80 -p 443:443 \
  -v /opt/syc/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v syc-caddy-data:/data -v syc-caddy-config:/config caddy:2
```

From your authenticated administration terminal, allow public HTTPS and certificate validation on the selected VPC:

```bash
gcloud compute firewall-rules create code-review-agent-web --project=hack-team-7-0ecb \
  --network="$NETWORK" --direction=INGRESS --action=ALLOW --rules=tcp:80,tcp:443 \
  --source-ranges=0.0.0.0/0 --target-tags=code-review-agent
```

Connect the MCP client to **`https://YOUR-DNS-NAME/mcp`**, transport **Streamable HTTP**, authentication **none**.
`MCP_ALLOWED_HOSTS` must match the actual public host (including port if your client sends one). DNS-rebinding
protection remains enabled. Anyone reaching this public anonymous service can trigger scans and fetch reports
for known scan IDs, consuming your project's Vertex quota; this is the explicitly requested access mode.

Run only one application container against this data directory. Scan timeout cleanup retains its lock until
blocking work finishes, so a timed-out scan may briefly remain busy while its bounded build/extraction exits.
Changing the model/location requires recreating the container with new environment values; keep `/data` mounted.

## Troubleshooting

* Model 404/unsupported location: verify the exact `GEMINI_MODEL` and Vertex location with your GCP administrator.
* 403 from Vertex: check the runtime identity's `roles/aiplatform.user`, quota-project permission, API enablement,
  and organization policy. Your `gcloud` CLI identity and the container's ADC identity may differ.
* ADC missing locally: complete **application-default** login and recreate the Podman secret/container.
* GCP 403 when pulling: grant registry reader to the **VM service account**, then repeat short-lived registry login.
* Startup rejects auth: set `ALLOW_UNAUTHENTICATED_PUBLIC=true` explicitly, or provide a valid `SERVICE_TOKEN`.
* MCP 421/403 through HTTPS: configure the exact host in `MCP_ALLOWED_HOSTS`; do not disable transport validation.
* Reports missing after replacement: mount the same named volume/persistent disk; do not use disposable container storage.

See `docs/compatibility.md` for what was actually executed. GCP deployment, Windows/Podman execution and real
Gemini access are not claimed verified without their corresponding successful runtime checks.
