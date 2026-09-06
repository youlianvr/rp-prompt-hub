#!/usr/bin/env python3
"""RP Prompt Hub builder.

Reads the curated manifest (manifest.json), pulls each prompt's content from the
collection and its full version history from git, then renders a single
self-contained static site (dist/index.html) — no server needed. Copy-to-clipboard
and version history work from file:// and from any static host.

Usage:
    python build_rp_hub.py
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "unfiltered" / "GOODboy-mode" / "prompts"
PROMPTS_PREFIX = "unfiltered/GOODboy-mode/prompts/"
HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
MANIFEST = HERE / "manifest.json"
# Output lives at the folder root (alongside sources) so `git subtree push`
# publishes dist artifacts and sources together — dist/ was dropped 2026-09-07.
OUT = HERE / "index.html"

# Single place for site-level settings.
CONFIG = {
    "title": "RP Prompt Hub",
    "subtitle": "Промпты для ролевых игр с ИИ — копируй в один клик, смотри историю версий",
    # Telegram username (без @) — кнопки обратной связи открывают
    # t.me/<username>?text=... с предзаполненным сообщением.
    "tg_username": "TheWorld_Machine",
}

# Reset point for version history shown in the hub: commits older than this
# ISO timestamp are excluded from the site (real git history is untouched).
# History accumulates again from this moment. Set to None to show all history.
RESET_AT = "2026-08-05T23:40:00+03:00"


def git(args):
    """Run git at repo root; return (stdout, returncode)."""
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false"] + args,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.stdout, r.returncode


def file_history(rel, follow=True):
    """Commits that touched the file (following renames).
    Returns [{hash, date, message, path}] where `path` is the file's actual
    path at that commit (differs from `rel` when the file was renamed).
    Set follow=False for files that are copies of another prompt (e.g. the
    Russian variant of the standard): without it, --follow walks back into
    the source prompt's history and the hub shows misleading versions."""
    cmd = ["log"] + (["--follow"] if follow else []) + \
        ["--format=%H%x1f%cI%x1f%s", "--name-status", "--", rel]
    out, rc = git(cmd)
    if rc != 0:
        return []
    commits, cur = [], None
    for line in out.splitlines():
        if "\x1f" in line:
            if cur is not None:
                commits.append(cur)
            h, d, m = line.split("\x1f", 2)
            cur = {"hash": h, "date": d, "message": m, "path": None}
        elif cur is not None and "\t" in line:
            parts = line.split("\t")
            st = parts[0]
            if (st.startswith(("R", "C")) and len(parts) >= 3) or (st in ("A", "M") and len(parts) >= 2):
                cur["path"] = parts[2] if st.startswith(("R", "C")) else parts[1]
    if cur is not None:
        commits.append(cur)
    # Keep only commits where the file actually lived inside the prompt
    # collection. Rename/copy chains that wander into other dirs (or AGENT.md
    # from the initial commit) are noise, not history.
    return [c for c in commits if c.get("path") and c["path"].startswith(PROMPTS_PREFIX)]


def file_at(path, commit):
    """Content of the file (at the given path) in a commit, or None."""
    out, rc = git(["show", f"{commit}:{path}"])
    return out if rc == 0 else None


def build():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest.get("prompts", [])

    prompts, skipped = [], []
    for entry in entries:
        fname = entry["file"]
        rel = "unfiltered/GOODboy-mode/prompts/" + fname
        path = PROMPTS_DIR / fname
        if not path.exists():
            skipped.append(fname)
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        hist = file_history(rel, follow=not entry.get("noFollow", False))
        cutoff = datetime.fromisoformat(RESET_AT) if RESET_AT else None
        versions = []
        for v in hist:
            if cutoff is not None:
                try:
                    if datetime.fromisoformat(v["date"]) < cutoff:
                        continue
                except ValueError:
                    pass
            path_at = v.get("path") or rel
            versions.append({**v, "content": file_at(path_at, v["hash"])})
        prompts.append(
            {
                "file": fname,
                "title": entry.get("title", fname),
                "description": entry.get("description", ""),
                "models": entry.get("models", []),
                "tags": entry.get("tags", []),
                "jb": bool(entry.get("jb", False)),
                "size": len(content),
                "content": content,
                "versions": versions,
                "versionCount": len(versions),
                "updated": versions[0]["date"]
                if versions
                else datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
            }
        )

    data = {"site": CONFIG, "prompts": prompts}
    json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Escape "</" so prompt text can never close the <script> tag.
    json_str = json_str.replace("</", "<\\/")

    template = TEMPLATE.read_text(encoding="utf-8")
    marker = "window.__PROMPTS_DATA__ = null;"
    if marker not in template:
        print("ERROR: placeholder not found in template.html", file=sys.stderr)
        sys.exit(1)
    html = template.replace(marker, "window.__PROMPTS_DATA__ = " + json_str)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    total = sum(p["size"] for p in prompts)
    print(f"OK: {len(prompts)} prompts ({total/1024:.0f} KB text), "
          f"skipped: {skipped or '-'}")
    print(f"-> {OUT} ({OUT.stat().st_size/1024:.0f} KB)")

    # Copy static pages and assets into dist/
    import shutil
    for name in ("tips.html", "about.html", "avatar.jpg"):
        src = HERE / name
        dst = OUT.parent / name
        if src.exists():
            try:
                shutil.copy2(src, dst)
            except PermissionError:
                if not dst.exists():
                    raise
                print(f"   (locked, kept existing) {dst.name}")
            print(f"-> {dst} ({dst.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    build()
