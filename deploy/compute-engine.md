# Compute Engine (single VM, Docker) — example, not verified by a deployment

For the bundled image and the requested public anonymous MCP deployment in `hack-team-7-0ecb`, follow
[`IMAGE_RUNBOOK.md`](IMAGE_RUNBOOK.md). This older guide shows the alternative external-repository mount workflow.

Status: these steps were **not executed** from the coding sandbox (no GCP identity was available). The image itself was
built and scanned locally with Docker (see `docs/compatibility.md`).

## 1. Build and push the image

```bash
PROJECT=YOUR_PROJECT_ID REGION=europe-west4 REPO=secureyourcode
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION   # once
docker build -t $REGION-docker.pkg.dev/$PROJECT/$REPO/secureyourcode:v2.3.1 .
gcloud auth configure-docker $REGION-docker.pkg.dev
docker push $REGION-docker.pkg.dev/$PROJECT/$REPO/secureyourcode:v2.3.1
```

## 2. VM with a service account that may call Vertex AI

```bash
gcloud iam service-accounts create syc-vm
gcloud projects add-iam-policy-binding $PROJECT \
  --member=serviceAccount:syc-vm@$PROJECT.iam.gserviceaccount.com --role=roles/aiplatform.user
gcloud projects add-iam-policy-binding $PROJECT \
  --member=serviceAccount:syc-vm@$PROJECT.iam.gserviceaccount.com --role=roles/artifactregistry.reader
gcloud compute instances create syc-demo --zone=$REGION-a --machine-type=e2-standard-4 \
  --image-family=cos-stable --image-project=cos-cloud \
  --service-account=syc-vm@$PROJECT.iam.gserviceaccount.com --scopes=cloud-platform
```

Container-Optimized OS ships Docker. The VM metadata server provides ADC to the container; do **not** copy JSON keys.

## 3. Put the trusted demo repository on the VM and start the container

```bash
gcloud compute ssh syc-demo --zone=$REGION-a
# on the VM. Container-Optimized OS has Docker but NO git, so clone through a container:
mkdir -p ~/demoshop ~/syc-data
docker run --rm -v ~/demoshop:/repo alpine/git:2.47.2 clone --depth 1 https://YOUR_PUBLIC_GIT_HOST/YOU/DemoShop.git /repo/DemoShop
#   alternative without a public Git URL — from your workstation:
#   tar -C demo -czf DemoShop.tgz DemoShop && gcloud compute scp DemoShop.tgz syc-demo:~ --zone=$REGION-a
#   then on the VM: tar -C ~/demoshop -xzf ~/DemoShop.tgz
sudo chown 1654:1654 ~/syc-data
docker-credential-gcr configure-docker --registries=$REGION-docker.pkg.dev
TOKEN=$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48)
docker run -d --name syc --restart unless-stopped -p 127.0.0.1:8000:8000 \
  -v ~/demoshop/DemoShop:/workspace/repo:ro -v ~/syc-data:/data \
  -e REPO_ROOT=/workspace/repo -e STATE_DIR=/data \
  -e GOOGLE_CLOUD_PROJECT=$PROJECT -e GOOGLE_CLOUD_LOCATION=global -e GEMINI_MODEL=YOUR_VERIFIED_MODEL_ID \
  -e SERVICE_TOKEN="$TOKEN" \
  $REGION-docker.pkg.dev/$PROJECT/$REPO/secureyourcode:v2.3.1
echo "keep this token: $TOKEN"
```

## 4. Use it over an SSH tunnel (port 8000 stays on VM loopback)

```bash
gcloud compute ssh syc-demo --zone=$REGION-a -- -L 8000:localhost:8000
# second terminal on your workstation
export SERVICE_TOKEN=...   # the token printed above
uv run python scripts/smoke_client.py --url http://127.0.0.1:8000 --via rest
uv run python scripts/smoke_client.py --url http://127.0.0.1:8000 --via mcp
```

Reports persist under `~/syc-data/runs/<scan_id>/report/` on the VM.
