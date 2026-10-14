"""report.json + offline report.html from one Report object; atomic directory publish."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .schemas import CATEGORIES, Report

_env = Environment(loader=PackageLoader("secureyourcode", "templates"), autoescape=select_autoescape(["html", "j2"], default=True))


def render_html(report: Report) -> str:
    template = _env.get_template("report.html.j2")
    findings = report.findings
    kept = {cat: [f for f in findings if f.decision == "keep" and f.category == cat] for cat in CATEGORIES}
    for group in kept.values():
        group.sort(key=lambda f: (-(f.grade or 0), f.file, f.start_line))
    return template.render(
        r=report,
        categories=CATEGORIES,
        kept=kept,
        downgraded=sorted([f for f in findings if f.decision == "downgrade"], key=lambda f: (-(f.grade or 0), f.file)),
        rejected=sorted([f for f in findings if f.decision == "reject"], key=lambda f: (f.file, f.start_line)),
        unreviewed=sorted([f for f in findings if f.decision == "unreviewed"], key=lambda f: (f.file, f.start_line)),
    )


def publish_report(report: Report, run_dir: Path) -> tuple[Path, Path | None, str | None]:
    """Write into a temp dir, then atomically rename to runs/<id>/report/. HTML failure does not block JSON."""
    tmp = run_dir / f".report-tmp-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True)
    html_error = None
    try:
        (tmp / "report.html").write_text(render_html(report), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - surfaced in status, never hidden
        html_error = f"{type(exc).__name__}: {exc}"
        if report.run.status == "complete":
            report.run.status = "partial"
        report.run.status_reasons.append(f"report.html could not be written: {html_error}")
    json_path = tmp / "report.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    final = run_dir / "report"
    if final.exists():
        shutil.rmtree(final)
    os.replace(tmp, final)
    html = final / "report.html"
    return final / "report.json", (html if html.is_file() else None), html_error
