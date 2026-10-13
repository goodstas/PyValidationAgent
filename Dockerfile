# syntax=docker/dockerfile:1
# SecureYourCode v2.3.1 — Python 3.12 + .NET 10 SDK (10.0.1xx band, matches global.json) + Graphify.
# Optional: behind a TLS-intercepting proxy, pass its CA bundle for network steps only (never stored in the image):
#   docker build --secret id=extra_ca,src=/path/to/ca-bundle.crt -t secureyourcode:v2.3.1 .
# Pinned SDK image: the 10.0.1xx feature band required by global.json (rollForward=latestPatch).
ARG DOTNET_SDK_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0.103-noble

# ---- stage 1: build + test the custom Roslyn analyzer (netstandard2.0) ----------------------------
FROM ${DOTNET_SDK_IMAGE} AS analyzer
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
WORKDIR /src
COPY scripts/docker-with-ca.sh /usr/local/bin/with-ca
COPY global.json ./
COPY roslyn/ ./roslyn/
RUN --mount=type=secret,id=extra_ca,required=false with-ca sh -ec '\
    dotnet restore roslyn/SecureYourCode.PerformanceAnalyzer.Tests --locked-mode; \
    dotnet test roslyn/SecureYourCode.PerformanceAnalyzer.Tests -c Release --no-restore; \
    dotnet build roslyn/SecureYourCode.PerformanceAnalyzer -c Release --no-restore -o /out'


# ---- stage 2: runtime --------------------------------------------------------------------------------
FROM ${DOTNET_SDK_IMAGE}
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
COPY scripts/docker-with-ca.sh /usr/local/bin/with-ca
RUN --mount=type=secret,id=extra_ca,required=false with-ca sh -ec '\
    apt-get update; \
    apt-get install -y --no-install-recommends python3.12 python3.12-venv python3-pip git ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    python3.12 -m pip install --no-cache-dir --break-system-packages uv==0.11.32'


WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=extra_ca,required=false with-ca uv sync --locked --no-dev --no-install-project --python /usr/bin/python3.12
COPY global.json ./
COPY src/ ./src/
RUN --mount=type=secret,id=extra_ca,required=false with-ca uv sync --locked --no-dev --python /usr/bin/python3.12
COPY --from=analyzer /out/SecureYourCode.PerformanceAnalyzer.dll /app/analyzer/SecureYourCode.PerformanceAnalyzer.dll

# Non-root runtime user (provided by the .NET image). Writable state only under /data.
RUN mkdir -p /data /workspace/repo && chown app:app /data
USER app
ENV HOME=/home/app \
    PATH=/app/.venv/bin:$PATH \
    ANALYZER_DLL=/app/analyzer/SecureYourCode.PerformanceAnalyzer.dll \
    REPO_ROOT=/workspace/repo \
    STATE_DIR=/data \
    SCAN_TIMEOUT_SECONDS=300 \
    MAX_REVIEW_CANDIDATES=16 \
    GOOGLE_GENAI_USE_VERTEXAI=true

# Warm the SDK for offline restore/build of a zero-PackageReference net10.0 web project (no repo copied in).
# Needs no network (targeting packs ship in the SDK image), so no `with-ca` / secret mount here.
RUN mkdir -p /tmp/warm && cd /tmp/warm \
 && printf '<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>' > Warm.csproj \
 && printf 'var app = WebApplication.CreateBuilder(args).Build();\napp.Run();\n' > Program.cs \
 && cp /app/global.json . && dotnet build -nodeReuse:false -p:UseSharedCompilation=false >/dev/null \
 && cd / && rm -rf /tmp/warm \
 && python -c "import graphify, deepagents, mcp; print('python deps ok')" \
 && python -m graphify --help >/dev/null

VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["secureyourcode"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
