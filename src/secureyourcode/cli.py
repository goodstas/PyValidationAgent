"""secureyourcode CLI: scan (blocking), demo-evaluate (out-of-band) and serve (REST + MCP)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, load_settings, validate_server_auth, validate_state_dir
from .demo_eval import DemoEvalError, run_demo_evaluate

EXIT_OK, EXIT_NOT_COMPLETE, EXIT_USAGE, EXIT_BUSY = 0, 1, 2, 3


def _scan(args: argparse.Namespace) -> int:
    from .service import Busy, ScanService
    from .workspace import LayoutError, validate_demo_layout

    settings = load_settings()
    repo = Path(args.repo).expanduser().resolve()
    try:
        validate_demo_layout(repo)
        validate_state_dir(settings, repo)
        service = ScanService(settings)
    except (LayoutError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        status = service.scan_blocking(repo, trigger="cli")
    except Busy:
        print("error: busy — another scan holds the lock for this STATE_DIR", file=sys.stderr)
        return EXIT_BUSY
    print(f"scan_id:      {status.scan_id}")
    print(f"status:       {status.status}")
    for reason in status.status_reasons:
        print(f"  reason:     {reason}")
    if status.error:
        print(f"error:        {status.error}")
    print("timings (s):  " + ", ".join(f"{k}={v}" for k, v in status.phase_timings.items()))
    print(f"report.json:  {status.report_json}")
    print(f"report.html:  {status.report_html}")
    return EXIT_OK if status.status == "complete" else EXIT_NOT_COMPLETE


def _demo_evaluate(args: argparse.Namespace) -> int:
    try:
        metrics = run_demo_evaluate(Path(args.report), Path(args.truth), Path(args.out) if args.out else None)
    except (DemoEvalError, FileNotFoundError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(metrics, indent=2))
    if args.out:
        print(f"wrote {args.out}", file=sys.stderr)
    return EXIT_OK


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app
    from .workspace import LayoutError, validate_demo_layout

    settings = load_settings()
    try:
        validate_server_auth(settings, args.host)
        validate_demo_layout(settings.repo_root)
        validate_state_dir(settings)
        app = create_app(settings)
    except (ConfigError, LayoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"serving REST + MCP on http://{args.host}:{args.port} (MCP at /mcp); repo={settings.repo_root}", file=sys.stderr)
    # Single process, no reload, no workers: required for the cross-process lock and Windows subprocess support.
    uvicorn.run(app, host=args.host, port=args.port, reload=False, workers=1, log_level="info")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secureyourcode", description="SecureYourCode v2.3.1 demo scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="run one blocking scan of a trusted demo repository")
    p.add_argument("--repo", required=True, help="absolute path of the trusted demo project (DemoShop layout)")
    p.add_argument("--wait", action="store_true", help="block until finished (the CLI always blocks)")
    p.set_defaults(func=_scan)

    p = sub.add_parser("demo-evaluate", help="out-of-band precision/recall against frozen ground truth")
    p.add_argument("--report", required=True)
    p.add_argument("--truth", required=True)
    p.add_argument("--out", default="demo_metrics.json", help="where to write demo_metrics.json (default: ./demo_metrics.json)")
    p.set_defaults(func=_demo_evaluate)

    p = sub.add_parser("serve", help="serve REST and MCP (Streamable HTTP at /mcp)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=_serve)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
