import time

from hypothesis import HealthCheck, given, settings, strategies as st

import handover

# The first text() draw builds Hypothesis's Unicode table (about 1.5 s cold), which trips too_slow.
settings.register_profile("cold", suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("cold")

NOW = int(time.time())
memory = st.fixed_dictionaries(
    {
        "keypath": st.sampled_from(["a.status", "b.todo", "c.x", "d.blocked.y"]),
        "content": st.text(max_size=30),
        "category": st.sampled_from([None, "status", "decision", "gotcha", "note"]),
        "created_at": st.integers(NOW - 30 * 86400, NOW),
    }
)
store = st.dictionaries(st.sampled_from(["p1", "p2", "p3"]), st.lists(memory, max_size=8))


def fake_daemon(projects):
    def call(path, body=None):
        if path == "projects":
            return {
                "projects": [
                    {"id": p, "last_updated_at": max((m["created_at"] for m in ms), default=0)}
                    for p, ms in projects.items()
                ]
            }
        assert body is not None
        return {"memories": projects[body["project_id"]]}

    return call


@given(store, st.integers(1, 30), st.lists(st.sampled_from(["p1", "p2"]), max_size=2))
def test_load_keeps_recent_rows_of_selected_projects(projects, days, only):
    rows = handover.load(fake_daemon(projects), days, only)
    cutoff = time.time() - days * 86400
    want = {
        (p, m["keypath"], m["content"], m["created_at"])
        for p, ms in projects.items()
        for m in ms
        if m["created_at"] >= cutoff and (not only or p in only)
    }
    assert {(r[0], r[1], r[2], r[4]) for r in rows} == want
    assert [r[4] for r in rows] == sorted((r[4] for r in rows), reverse=True)


@given(store)
def test_every_row_in_exactly_one_section(projects):
    rows = handover.load(fake_daemon(projects), 30, [])
    groups = handover.sections(rows)
    assert sorted(sum(groups.values(), [])) == sorted(rows)


@given(st.text())
def test_render_escapes_content(text):
    page = handover.render([("p", "k.todo", text + "<script>x</script>", "status", 0)], 7)
    assert "<script>" not in page
    assert page.count("<html") == 1


def test_needs_section_matches_todo_keypaths():
    groups = handover.sections(
        [("p", "work.todo", "c", "status", 0), ("p", "work.todos_done", "c", "status", 0)]
    )
    assert [r[1] for r in groups["needs"]] == ["work.todo"]
