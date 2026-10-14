from __future__ import annotations

import json
from pathlib import Path

from secureyourcode.demo_eval import GroundTruth
from secureyourcode.roslyn_runner import SELECTED_RULE_IDS, candidate_id, parse_sarif, run_roslyn
from secureyourcode.workspace import compute_fingerprint, make_build_copy, stage_source

from .conftest import ANALYZER, APP_ROOT, DEMO, needs_dotnet


def _sarif(results: list[dict], version: str = "2.1.0", base: dict | None = None) -> dict:
    run: dict = {"results": results}
    if base:
        run["originalUriBaseIds"] = base
    return {"version": version, "runs": [run]}


def _res(rule: str, uri: str, line: int, end: int | None = None, base_id: str | None = None) -> dict:
    art = {"uri": uri}
    if base_id:
        art["uriBaseId"] = base_id
    region = {"startLine": line}
    if end:
        region["endLine"] = end
    return {"ruleId": rule, "message": {"text": f"{rule} msg"}, "locations": [{"physicalLocation": {"artifactLocation": art, "region": region}}]}


def _layout(tmp: Path) -> tuple[Path, Path]:
    staged, build = tmp / "staged", tmp / "build dir"
    for root in (staged, build):
        (root / "Sub Dir").mkdir(parents=True)
        (root / "Sub Dir" / "A.cs").write_text("line1\nline2\nline3\n")
    return staged, build


def test_sarif_uri_normalisation_and_validation(tmp_outside: Path) -> None:
    staged, build = _layout(tmp_outside)
    abs_uri = (build / "Sub Dir" / "A.cs").resolve().as_uri()  # percent-encoded file:// URI
    results = [
        _res("CA3001", abs_uri, 2),
        _res("CA3001", abs_uri, 2),  # duplicate collapses
        _res("PERF001", "Sub%20Dir\\A.cs", 1),  # relative, percent-encoded, Windows separators
        _res("PERF003", "A.cs", 1, base_id="SRCROOT"),
        _res("CA5350", (tmp_outside / "elsewhere.cs").as_uri(), 1),  # outside build copy
        _res("CA5394", abs_uri, 99),  # invalid line range
        _res("CA1850", abs_uri, 1),  # unselected rule ignored
    ]
    base = {"SRCROOT": {"uri": (build / "Sub Dir").resolve().as_uri() + "/"}}
    sarif = tmp_outside / "x.sarif"
    sarif.write_text(json.dumps(_sarif(results, base=base)))
    r = parse_sarif(sarif, build, staged)
    assert r.status == "ok"
    got = [(c.rule_id, c.file, c.start_line) for c in r.candidates]
    assert sorted(got) == sorted([("CA3001", "Sub Dir/A.cs", 2), ("PERF001", "Sub Dir/A.cs", 1), ("PERF003", "Sub Dir/A.cs", 1)])
    assert any("outside the build copy" in d for d in r.dropped_locations)
    assert any("invalid line range" in d for d in r.dropped_locations)
    c = next(c for c in r.candidates if c.rule_id == "CA3001")
    assert c.candidate_id == candidate_id("CA3001", "Sub Dir/A.cs", 2, 2) and c.excerpt == "line2" and c.category == "Security"
    assert "CA5350" in r.missing_rule_ids


def test_sarif_version_and_garbage_are_failures(tmp_outside: Path) -> None:
    staged, build = _layout(tmp_outside)
    p = tmp_outside / "v.sarif"
    p.write_text(json.dumps(_sarif([], version="2.0.0")))
    assert parse_sarif(p, build, staged).status == "failed"
    p.write_text("not json")
    assert parse_sarif(p, build, staged).status == "failed"


@needs_dotnet
def test_real_build_emits_all_eight_rules_inside_truth_ranges(tmp_outside: Path) -> None:
    """Integration gate: real dotnet build of the zero-PackageReference DemoShop emits every selected ID."""
    staged = tmp_outside / "staged"
    stage_source(DEMO, staged)
    build = tmp_outside / "b" / "src"
    make_build_copy(staged, build)
    r = run_roslyn(staged, build, ANALYZER, APP_ROOT / "global.json", 300)
    assert r.status == "ok", r.error + r.log_tail if r.error else ""
    assert r.missing_rule_ids == [] and set(r.emitted_rule_ids) == set(SELECTED_RULE_IDS)
    truth = GroundTruth.model_validate_json((APP_ROOT / "demo/ground-truth.json").read_text())
    assert truth.fixture_fingerprint == compute_fingerprint(DEMO), "fixture changed since ground truth was frozen"
    for t in truth.entries:
        hits = [c for c in r.candidates if c.rule_id == t.rule_id and c.file == t.file and t.start_line <= c.start_line <= t.end_line]
        if t.label == "positive":
            assert hits, f"{t.id}: expected {t.rule_id} in {t.file}:{t.start_line}-{t.end_line}"
    perf_negatives = [t for t in truth.entries if t.label == "negative" and t.rule_id.startswith("PERF")]
    for t in perf_negatives:
        assert not [c for c in r.candidates if c.rule_id == t.rule_id and c.file == t.file and t.start_line <= c.start_line <= t.end_line], t.id
    # the original fixture is never built in place
    assert not (DEMO / "bin").exists() and not (DEMO / "obj").exists()
