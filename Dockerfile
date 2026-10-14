# syntax=docker/dockerfile:1
# SecureYourCode v2.3.1 — Python 3.12 + .NET 10 SDK (10.0.1xx band, matches global.json) + Graphify.
# Optional: behind a TLS-intercepting proxy, pass its CA bundle for network steps only (never stored in the image):
#   docker build --secret id=extra_ca,src=/path/to/ca-bundle.crt -t secureyourcode:v2.3.1 .
# Use the official SDK archive so builds do not require MCR's regional blob hosts.
# linux/amd64; SHA-512 from Microsoft's .NET 10 release metadata.
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS toolchain
ENV DOTNET_ROOT=/usr/share/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
COPY scripts/docker-with-ca.sh /usr/local/bin/with-ca
RUN --mount=type=secret,id=extra_ca,required=false with-ca sh -ec '\
    test "$(dpkg --print-architecture)" = amd64; \
    apt-get update; \
    apt-get install -y --no-install-recommends python3.12 python3.12-venv python3-pip git ca-certificates curl \
        libc6 libgcc-s1 libicu74 libssl3t64 libstdc++6 tzdata zlib1g; \
    rm -rf /var/lib/apt/lists/*; \
    curl --fail --location --retry 3 -o /tmp/dotnet.tar.gz https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.103/dotnet-sdk-10.0.103-linux-x64.tar.gz; \
    echo "bab94f13c57b2ac821d4924fe66084be9b44c41761ff7ff64522c8f7aba345659d31258401dcec31cc3cf6ccae1d012623075aca1c9b9165bcfe5ba9abda1c0c  /tmp/dotnet.tar.gz" | sha512sum --check; \
    mkdir -p /usr/share/dotnet; tar -xzf /tmp/dotnet.tar.gz -C /usr/share/dotnet; \
    ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet; rm /tmp/dotnet.tar.gz; \
    python3.12 -m pip install --no-cache-dir --break-system-packages uv==0.11.32; \
    groupadd --gid 1654 app; useradd --uid 1654 --gid 1654 --create-home app'

# Build and test from a read-only context mount, retaining only runtime files.
# Few large layers also work with Docker's copy-based vfs storage driver.
WORKDIR /app
RUN --mount=type=bind,target=/build,readonly --mount=type=secret,id=extra_ca,required=false \
    with-ca sh /build/scripts/docker-install-app.sh

USER app
ENV HOME=/home/app \
    PATH=/app/.venv/bin:$PATH \
    ANALYZER_DLL=/app/analyzer/SecureYourCode.PerformanceAnalyzer.dll \
    REPO_ROOT=/workspace/repo \
    STATE_DIR=/data \
    SCAN_TIMEOUT_SECONDS=300 \
    MAX_REVIEW_CANDIDATES=16 \
    GOOGLE_GENAI_USE_VERTEXAI=true \
    MODEL_PROVIDER=vertex
VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["secureyourcode"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
