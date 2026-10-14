from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from secureyourcode.graphify_runner import GraphSession, build_or_update_graph, choose_host_target, normalize_graph_path
from secureyourcode.workspace import stage_source


def _graph(state: Path, demo: Path) -> tuple:
    src = state / "source"
    st = stage_source(demo, src)
    return build_or_update_graph(src, state / "graph", st.fingerprint, st.files, 120), st


def test_graph_built_cached_updated_and_deleted(demo_copy: Path, tmp_outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHIFY_OUT", str(tmp_outside / "should-not-be-used"))
    state = tmp_outside / "state"
    g1, _ = _graph(state, demo_copy)
    assert g1.status == "built" and g1.node_count and not (tmp_outside / "should-not-be-used").exists()
    assert not (demo_copy / "graphify-out").exists() and not (state / "source" / "graphify-out").exists()

    g2, _ = _graph(state, demo_copy)
    assert g2.status == "cached"

    (demo_copy / "Services/BannerColorPicker.cs").write_text(
        (demo_copy / "Services/BannerColorPicker.cs").read_text().replace("public string NextColor()", "public string PickBannerColor()")
    )
    g3, _ = _graph(state, demo_copy)
    assert g3.status == "updated"
    labels = {n["label"] for n in json.loads(g3.graph_path.read_text())["nodes"]}
    assert ".PickBannerColor()" in labels and ".NextColor()" not in labels

    (demo_copy / "Services/SessionStore.cs").unlink()
    g4, _ = _graph(state, demo_copy)
    nodes = json.loads(g4.graph_path.read_text())["nodes"]
    assert g4.status == "updated"
    assert not [n for n in nodes if (n.get("source_file") or "").endswith("SessionStore.cs")]


def test_host_target_is_deterministic_and_segment_bounded(tmp_outside: Path) -> None:
    graph = {
        "nodes": [
            {"id": "z_file", "source_file": "Services/ReportCache.cs"},
            {"id": "a_file", "source_file": "Services/ReportCache.cs"},
            {"id": "evil", "source_file": "MyServices/ReportCache.cs"},
            {"id": "abs", "source_file": str(tmp_outside / "snap/Other.cs")},
        ]
    }
    b1 = SimpleNamespace(candidate_id="bbb", file="Services/ReportCache.cs", rule_id="PERF004")
    b0 = SimpleNamespace(candidate_id="aaa", file="Other.cs", rule_id="CA5350")
    assert choose_host_target(graph, [b1], tmp_outside / "snap")[0] == "a_file"
    assert choose_host_target(graph, [b1, b0], tmp_outside / "snap")[0] == "abs"
    assert normalize_graph_path("./x\\y.cs", None) == "x/y.cs"
    # 'ReportCache.cs' must not match 'MyServices/ReportCache.cs' via substring for file 'Services/ReportCache.cs'
    only_evil = {"nodes": [{"id": "evil", "source_file": "MyServices/ReportCache.cs"}]}
    node, reason = choose_host_target(only_evil, [b1], tmp_outside)
    assert node == "evil" and "no baseline node matched" in reason


async def test_real_graphify_mcp_session_host_and_reviewer_calls(demo_copy: Path, tmp_outside: Path) -> None:
    g, _ = _graph(tmp_outside / "state", demo_copy)
    graph = json.loads(g.graph_path.read_text())
    target, reason = choose_host_target(graph, [SimpleNamespace(candidate_id="0", file="Services/ReportCache.cs", rule_id="PERF004")], tmp_outside)
    async with GraphSession(g.graph_path, cwd=tmp_outside) as session:
        names = sorted(t.name for t in session.tools)
        assert names == ["get_neighbors", "get_node", "graph_stats", "query_graph", "shortest_path"]
        hq = await session.host_query(target, reason)
        assert hq.ok and hq.tool == "get_neighbors" and "ReportCache" in hq.result_excerpt and hq.result_bytes <= 8192
        tool = {t.name: t for t in session.counted_tools("PerformanceReviewer")}["get_node"]
        out = await tool.ainvoke({"label": "ReportCache"})
        assert "<untrusted_graph_data" in out and "ReportCache" in out
        assert session.host_calls == 1 and session.reviewer_calls == {"PerformanceReviewer": 1}
