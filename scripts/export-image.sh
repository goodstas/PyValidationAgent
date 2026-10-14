#!/usr/bin/env bash
# Export an already built image; no registry credentials or build are required.
set -euo pipefail
image=${1:-code-review-agent:v1.0}
output_dir=${2:-../artifacts}
mkdir -p "$output_dir"
archive=code-review-agent-v1.0-linux-amd64.tar.gz
docker image inspect "$image" --format '{{.Os}}/{{.Architecture}} {{.Id}}' > "$output_dir/IMAGE_ID.txt"
docker save "$image" | gzip -1 > "$output_dir/$archive.part"
mv "$output_dir/$archive.part" "$output_dir/$archive"
(
  cd "$output_dir"
  sha256sum "$archive" > SHA256SUMS
)
printf 'Exported %s/%s\n' "$output_dir" "$archive"
