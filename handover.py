"""Render a hand-over page from memstate and open it in the browser.

  py -3 handover.py [--out handover.html] [--no-open] [--days 7] [--project ID ...] [--addr HOST:PORT]

Reads the memstate daemon's HTTP API (MEMSTATE_ADDR). Writes one local HTML file.
Sends nothing anywhere. Costs no AI tokens, so it can run from a Stop hook (with --no-open).
"""

import argparse
import html
import json
import os
import pathlib
import re
import time
import urllib.request
import webbrowser
from collections import defaultdict

# ponytail: keyword match on keypath and category; add a "needs_user" category to memstate if this misses items.
NEEDS = re.compile(r"(^|[._])(todo|blocked|needs?_?(you|user)|unfinished|next_steps?|handoff)([._]|$)")

SECTIONS = [
    ("needs", "Needs you", lambda r: NEEDS.search(r[1]) or r[3] in ("todo", "blocked")),
    ("status", "Status", lambda r: r[3] == "status"),
    ("decisions", "Decisions", lambda r: r[3] == "decision"),
    ("gotchas", "Gotchas", lambda r: r[3] == "gotcha"),
    ("other", "Other notes", lambda _: True),
]

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#555;--line:#ddd;--card:#f7f7f5;--link:#0645ad}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e8e8;--mut:#aaa;--line:#333;--card:#1e1e1e;--link:#7ab3ff}}
body{margin:0 auto;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,Segoe UI,Roboto,sans-serif;max-width:1100px}
h1{font-size:1.5em;margin:.2em 0}h2{font-size:1.25em;border-bottom:1px solid var(--line);padding-bottom:.2em;margin-top:1.6em}
h3{font-size:1.05em;margin:.8em 0 .3em}a{color:var(--link)}.mut{color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:10px 0}
.card pre{white-space:pre-wrap;word-break:break-word;margin:.4em 0 0;font:13px/1.4 ui-monospace,Consolas,monospace}
code{font:13px ui-monospace,Consolas,monospace}
"""


def daemon(addr):
    """Return a function that calls the memstate daemon at addr and decodes the JSON reply."""

    def call(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"http://{addr}/api/v1/{path}",
            data,
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    return call


def load(call, days, only):
    """Latest live memories newer than `days`, newest first, as (project, keypath, content, category, created_at)."""
    cutoff = time.time() - days * 86400
    rows = []
    for p in call("projects")["projects"]:
        if p["last_updated_at"] < cutoff or (only and p["id"] not in only):
            continue
        body = {"project_id": p["id"], "keypath": "", "include_content": True}
        for m in call("keypaths", body)["memories"]:
            if m["created_at"] >= cutoff:
                rows.append((p["id"], m["keypath"], m["content"], m.get("category") or "", m["created_at"]))
    return sorted(rows, key=lambda r: -r[4])


def sections(rows):
    """Put each row in the first section whose test matches. Keeps the input order."""
    out = defaultdict(list)
    for r in rows:
        out[next(key for key, _, test in SECTIONS if test(r))].append(r)
    return out


def card(r):
    e = html.escape
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r[4]))
    cat = f" · {e(r[3])}" if r[3] else ""
    return (
        f'<div class="card"><code>{e(r[1])}</code> <span class="mut">{e(r[0])} · {when}{cat}</span>'
        f"<pre>{e(r[2])}</pre></div>"
    )


def render(rows, days):
    groups = sections(rows)
    now = time.strftime("%Y-%m-%d %H:%M")
    toc = " · ".join(f'<a href="#{k}">{t} ({len(groups[k])})</a>' for k, t, _ in SECTIONS)
    body = [
        "<h1>State of all tasks</h1>",
        f'<p class="mut">Last update: {now}. From memstate, last {days} days, {len(rows)} memories.</p>',
        f"<p>{toc}</p>",
    ]
    for key, title, _ in SECTIONS:
        body.append(f'<h2 id="{key}">{title}</h2>')
        by_project = defaultdict(list)
        for r in groups[key]:
            by_project[r[0]].append(r)
        for project, items in by_project.items():
            body.append(f"<h3>{html.escape(project)}</h3>")
            body.extend(card(r) for r in items)
        if not groups[key]:
            body.append('<p class="mut">Nothing.</p>')
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f"<title>State of all tasks, {now[:10]}</title><style>{CSS}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


def main():
    ap = argparse.ArgumentParser(description="Render a hand-over page from memstate.")
    ap.add_argument("--out", default="handover.html")
    ap.add_argument("--no-open", action="store_true", help="do not open the page in the browser")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--project", action="append", default=[])
    ap.add_argument("--addr", default=os.environ.get("MEMSTATE_ADDR", "127.0.0.1:8767"))
    a = ap.parse_args()
    rows = load(daemon(a.addr), a.days, a.project)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(rows, a.days))
    os.replace(tmp, a.out)  # readers never see a half-written page
    uri = pathlib.Path(a.out).resolve().as_uri()
    print(f"{uri}: {len(rows)} memories")
    if not a.no_open:
        webbrowser.open(uri)


if __name__ == "__main__":
    main()
