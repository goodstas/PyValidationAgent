"""Out-of-band demo quality evaluation against frozen ground truth (never writes report.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .schemas import Finding, Report
from .workspace import compute_fingerprint


class TruthEntry(BaseModel):
    id: str
    label: Literal["positive", "negative"]
    rule_id: str
    category: Literal["Security", "CPU & Amplification", "Concurrency", "Memory & Allocation"]
    file: str
    start_line: int
    end_line: int
    rationale: str


class GroundTruth(BaseModel):
    fixture_fingerprint: str
    scoring_version: str
    entries: list[TruthEntry]


class DemoEvalError(RuntimeError):
    pass


def freeze_ground_truth(entries: list[dict] | list[TruthEntry], fixture_root: Path, out_path: Path, scoring_version: str) -> GroundTruth:
    """Write ground truth with the fixture's current fingerprint. `entries` are validated TruthEntry rows or dicts."""
    rows = [e if isinstance(e, TruthEntry) else TruthEntry.model_validate(e) for e in entries]
    truth = GroundTruth(fixture_fingerprint=compute_fingerprint(fixture_root), scoring_version=scoring_version, entries=rows)
    out_path.write_text(truth.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return truth


def _ratio(num: int, den: int) -> float | str:
    return round(num / den, 4) if den else "undefined"


def _roslyn_matches(f: Finding, t: TruthEntry) -> bool:
    return f.origin == "roslyn" and f.rule_id == t.rule_id and f.file == t.file and t.start_line <= f.start_line <= t.end_line


def _ai_matches(f: Finding, t: TruthEntry) -> bool:
    return f.origin == "ai" and f.file == t.file and f.category == t.category and f.start_line <= t.end_line and t.start_line <= f.end_line


def _overlaps(f: Finding, t: TruthEntry) -> bool:
    return f.file == t.file and f.start_line <= t.end_line and t.start_line <= f.end_line


def compute_metrics(report: Report, truth: GroundTruth) -> dict:
    if report.scoring_version != truth.scoring_version:
        raise DemoEvalError(
            f"Scoring version mismatch: report {report.scoring_version!r} vs ground truth {truth.scoring_version!r}."
        )
    if report.run.status != "complete":
        raise DemoEvalError(f"Report status is {report.run.status!r}; demo metrics require a 'complete' live scan.")
    if report.provenance.source_fingerprint != truth.fixture_fingerprint:
        raise DemoEvalError(
            "Report source fingerprint does not match the frozen fixture fingerprint; the scanned source is not the seeded fixture."
        )

    predictions = [f for f in report.findings if f.decision in ("keep", "downgrade")]
    positives = [t for t in truth.entries if t.label == "positive"]
    negatives = [t for t in truth.entries if t.label == "negative"]

    # Collapse same-rule Roslyn predictions inside one positive range into one metric prediction.
    groups: list[list[Finding]] = []
    grouped: set[str] = set()
    for t in positives:
        same = [f for f in predictions if f.candidate_id not in grouped and _roslyn_matches(f, t)]
        if same:
            groups.append(same)
            grouped.update(f.candidate_id for f in same)
    groups.extend([f] for f in predictions if f.candidate_id not in grouped)

    matched_groups: set[int] = set()
    tp_rows, fn_rows = [], []
    for t in sorted(positives, key=lambda e: e.id):
        choice = None
        for kind in (_roslyn_matches, _ai_matches):  # prefer the Roslyn baseline
            for i, g in enumerate(groups):
                if i not in matched_groups and any(kind(f, t) for f in g):
                    choice = i
                    break
            if choice is not None:
                break
        if choice is None:
            fn_rows.append({"truth_id": t.id, "rule_id": t.rule_id, "file": t.file})
        else:
            matched_groups.add(choice)
            tp_rows.append({"truth_id": t.id, "candidate_ids": [f.candidate_id for f in groups[choice]]})

    fp_rows = []
    for i, g in enumerate(groups):
        if i in matched_groups:
            continue
        f = g[0]
        neg = next((t.id for t in negatives if _overlaps(f, t)), None)
        fp_rows.append(
            {
                "candidate_ids": [x.candidate_id for x in g],
                "display_id": f.display_id,
                "file": f.file,
                "line": f.start_line,
                "decision": f.decision,
                "explicit_negative": neg,
            }
        )

    tp, fp, fn = len(tp_rows), len(fp_rows), len(fn_rows)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    if isinstance(precision, float) and isinstance(recall, float) and (precision + recall) > 0:
        f1: float | str = round(2 * precision * recall / (precision + recall), 4)
    else:
        f1 = "undefined"
    return {
        "scan_id": report.run.scan_id,
        "evaluated_report_fingerprint": report.provenance.source_fingerprint,
        "fixture_fingerprint": truth.fixture_fingerprint,
        "scoring_version": truth.scoring_version,
        "predictions_counted": len(groups),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp_rows,
        "false_positives": fp_rows,
        "false_negatives": fn_rows,
        "rejected_or_unreviewed_not_counted": len(report.findings) - len(predictions),
    }


def _same_file(a: Path, b: Path) -> bool:
    """True if the two paths name the same file, through relative paths, symlinks or hard links."""
    try:
        if a.exists() and b.exists():
            return os.path.samefile(a, b)
    except OSError:
        pass
    return a.resolve() == b.resolve()


def run_demo_evaluate(report_path: Path, truth_path: Path, out_path: Path | None) -> dict:
    report_path, truth_path = Path(report_path), Path(truth_path)
    if out_path is not None:
        for label, inp in (("report", report_path), ("ground-truth", truth_path)):
            if _same_file(Path(out_path), inp):
                raise DemoEvalError(f"--out must not be an input file: {out_path} is the {label} path (metrics would overwrite it)")
    report = Report.model_validate_json(Path(report_path).read_text(encoding="utf-8"))
    truth = GroundTruth.model_validate_json(Path(truth_path).read_text(encoding="utf-8"))
    metrics = compute_metrics(report, truth)
    if out_path is not None:
        Path(out_path).write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics
