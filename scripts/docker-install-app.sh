#!/bin/sh
# Called only by Dockerfile with the build context mounted read-only at /build.
set -eu
cd /app
cp /build/pyproject.toml /build/uv.lock /build/README.md /build/global.json .
cp -r /build/src ./src
uv sync --locked --no-dev --no-cache --python /usr/bin/python3.12

mkdir -p /tmp/analyzer /app/analyzer
cp /build/global.json /tmp/analyzer/
cp -r /build/roslyn /tmp/analyzer/
dotnet restore /tmp/analyzer/roslyn/SecureYourCode.PerformanceAnalyzer.Tests --locked-mode
dotnet test /tmp/analyzer/roslyn/SecureYourCode.PerformanceAnalyzer.Tests -c Release --no-restore \
    -nodeReuse:false -p:UseSharedCompilation=false -maxcpucount:2
dotnet build /tmp/analyzer/roslyn/SecureYourCode.PerformanceAnalyzer -c Release --no-restore \
    -nodeReuse:false -p:UseSharedCompilation=false -maxcpucount:2 -o /app/analyzer
rm -rf /tmp/analyzer /root/.nuget /root/.dotnet /root/.cache

mkdir -p /workspace/repo /data /app/demo /app/scripts
cp -r /build/demo/DemoShop/. /workspace/repo/
cp /build/demo/ground-truth.json /app/demo/
cp /build/scripts/smoke_client.py /build/scripts/vertex_probe.py /app/scripts/
# Normalize restrictive checkout permissions for the non-root runtime user.
chmod -R a+rX /app /workspace/repo
chown app:app /data

# Warm an ordinary zero-dependency project under the runtime UID. Source is not the demo.
mkdir -p /tmp/warm
cat > /tmp/warm/Warm.csproj <<'EOF'
<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>
EOF
cat > /tmp/warm/Program.cs <<'EOF'
var app = WebApplication.CreateBuilder(args).Build();
app.Run();
EOF
cp /app/global.json /tmp/warm/
chown -R app:app /tmp/warm
runuser -u app -- dotnet build /tmp/warm/Warm.csproj -nodeReuse:false -p:UseSharedCompilation=false
rm -rf /tmp/warm
runuser -u app -- /app/.venv/bin/python -c 'import graphify, deepagents, mcp, secureyourcode.cli; print("runtime imports ok")'
runuser -u app -- /app/.venv/bin/python -m graphify --help >/dev/null
