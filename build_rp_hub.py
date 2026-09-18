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
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
# Prompts live inside the project since 2026-09-18 (decoupled from the
# unfiltered/GOODboy-mode collection). LEGACY_PREFIX keeps the pre-move
# history visible: old commits stored the files under the collection path,
# and the history filter below must accept both to not blank out versions.
PROMPTS_DIR = HERE / "prompts"
PROMPTS_PREFIX = "projects/rp-hub/prompts/"
LEGACY_PREFIX = "unfiltered/GOODboy-mode/prompts/"
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

# Toggleable rule blocks. Markers live in the prompt files; the builder
# extracts them so the site can show per-block switches in the
# Customization tab. Options marked `advanced` are heavy-flavour rules
# (on by default, easy to drop). Core rules carry no markers and are
# always part of the prompt.
OPTION_RE = re.compile(
    r"<!--\s*OPTION:([a-zA-Z0-9_-]+)\s*-->(.*?)<!--\s*/OPTION\s*-->",
    re.DOTALL,
)

OPTIONS_META = {
    "tempo": {
        "label": "Контроль темпа",
        "description": "Запрет самовольных таймскипов и пересказа («они поели, поговорили, к вечеру пошли домой»). Один момент — сколько угодно ходов, после реплики игрока — реакция и стоп.",
    },
    "depth": {
        "label": "Глубина реакций",
        "description": "Запрет дежурных поверхностных ответов: подтекст, личная заинтересованность, конкретная память персонажа вместо первого очевидного ответа.",
    },
    "format": {
        "label": "Чистое форматирование",
        "description": "Без выделений в прозе, без дробления «Точка. После. Каждого. Слова.», без инородных слов без внутриигровой причины.",
    },
    "blood": {
        "label": "Кровь и мясо (§13)",
        "description": "Жёсткий телесный бой: раны болеют и остаются, без исчезающей крови. Тяжёлый блок — отключи для лёгких или детских сюжетов.",
        "advanced": True,
    },
}


def extract_options(text):
    """Return ([{id,label,description,advanced}], positions preserved).
    Options are listed in file order; unknown ids are skipped with a
    console warning so a typo never silently ships to the site."""
    found, warned = [], set()
    for m in OPTION_RE.finditer(text):
        oid = m.group(1)
        meta = OPTIONS_META.get(oid)
        if meta is None:
            if oid not in warned:
                print(f"WARNING: unknown option id '{oid}' in prompt file", file=sys.stderr)
                warned.add(oid)
            continue
        found.append({"id": oid, **meta})
    return found


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
    return [c for c in commits if c.get("path") and
            (c["path"].startswith(PROMPTS_PREFIX) or c["path"].startswith(LEGACY_PREFIX))]


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
        rel = PROMPTS_PREFIX + fname
        path = PROMPTS_DIR / fname
        if not path.exists():
            skipped.append(fname)
            continue

        def load_part(part_fname, follow):
            part_rel = PROMPTS_PREFIX + part_fname
            part_path = PROMPTS_DIR / part_fname
            if not part_path.exists():
                return None, [], []
            raw = part_path.read_text(encoding="utf-8", errors="replace")
            hist = file_history(part_rel, follow=follow)
            cutoff = datetime.fromisoformat(RESET_AT) if RESET_AT else None
            versions = []
            for v in hist:
                if cutoff is not None:
                    try:
                        if datetime.fromisoformat(v["date"]) < cutoff:
                            continue
                    except ValueError:
                        pass
                path_at = v.get("path") or part_rel
                versions.append({**v, "content": file_at(path_at, v["hash"])})
            return raw, versions, extract_options(raw)

        content, versions, options = load_part(fname, follow=not entry.get("noFollow", False))
        prompt = {
            "file": fname,
            "kind": "chat",
            "title": entry.get("title", fname),
            "description": entry.get("description", ""),
            "models": entry.get("models", []),
            "tags": entry.get("tags", []),
            "jb": bool(entry.get("jb", False)),
            "size": len(content),
            "content": content,
            "options": options,
            "versions": versions,
            "versionCount": len(versions),
            "updated": versions[0]["date"]
            if versions
            else datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
        }

        sys_fname = entry.get("fileSystem")
        if sys_fname:
            sys_path = PROMPTS_DIR / sys_fname
            if not sys_path.exists():
                skipped.append(sys_fname)
            else:
                sys_raw, sys_versions, sys_options = load_part(
                    sys_fname, follow=not entry.get("noFollowSystem", entry.get("noFollow", False))
                )
                prompt["kind"] = "pair"
                prompt["fileSystem"] = sys_fname
                prompt["contentSystem"] = sys_raw
                prompt["sizeSystem"] = len(sys_raw)
                # Options govern the system part (that is where the rules live).
                prompt["options"] = sys_options or options
                prompt["versionsSystem"] = sys_versions
                prompt["versionCountSystem"] = len(sys_versions)
                prompt["updatedSystem"] = (
                    sys_versions[0]["date"]
                    if sys_versions
                    else datetime.fromtimestamp(sys_path.stat().st_mtime).astimezone().isoformat()
                )

        prompts.append(prompt)

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
    total = sum(p["size"] + p.get("sizeSystem", 0) for p in prompts)
    kinds = [p["kind"] for p in prompts]
    print(f"OK: {len(prompts)} prompts ({sum(1 for k in kinds if k == 'pair')} pairs) "
          f"({total/1024:.0f} KB text), skipped: {skipped or '-'}")
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
