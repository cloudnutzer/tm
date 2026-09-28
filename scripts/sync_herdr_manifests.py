#!/usr/bin/env python3
"""Vendor herdr's agent screen manifests into src/tmux_manager/agent_manifests/.

    python scripts/sync_herdr_manifests.py COMMIT [--clone DIR]

Copies every src/detect/manifests/*.toml and the LICENSE of herdr at COMMIT
and rewrites NOTICE. Without --clone the files come from GitHub; with --clone
they are read from a local herdr checkout via ``git show COMMIT:path``, which
also works offline. Existing manifests that are gone upstream are removed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = "herdrdev/herdr"
MANIFEST_DIR = "src/detect/manifests"
TARGET = Path(__file__).resolve().parent.parent / "src" / "tmux_manager" / "agent_manifests"

NOTICE = """\
The *.toml files in this directory are the agent screen manifests of herdr
(https://github.com/{repo}), copied unchanged from {manifest_dir} at commit
{commit}.

herdr is licensed under the Apache License 2.0; see LICENSE in this directory.
tm evaluates them with its own Python port of herdr's rule engine
(src/tmux_manager/manifests.py). Refresh with:

    python scripts/sync_herdr_manifests.py <commit>
"""


def _github(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "tm-sync-herdr-manifests"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data: bytes = response.read()
    return data


def fetch_github(commit: str) -> dict[str, bytes]:
    listing = json.loads(
        _github(f"https://api.github.com/repos/{REPO}/contents/{MANIFEST_DIR}?ref={commit}")
    )
    raw = f"https://raw.githubusercontent.com/{REPO}/{commit}"
    files = {
        entry["name"]: _github(f"{raw}/{MANIFEST_DIR}/{entry['name']}")
        for entry in listing
        if entry["name"].endswith(".toml")
    }
    files["LICENSE"] = _github(f"{raw}/LICENSE")
    return files


def fetch_clone(commit: str, clone: Path) -> dict[str, bytes]:
    def show(path: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(clone), "show", f"{commit}:{path}"], capture_output=True, check=True
        ).stdout

    names = subprocess.run(
        ["git", "-C", str(clone), "ls-tree", "--name-only", commit, f"{MANIFEST_DIR}/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    files = {Path(name).name: show(name) for name in names if name.endswith(".toml")}
    files["LICENSE"] = show("LICENSE")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("commit", help="full herdr commit hash")
    parser.add_argument("--clone", type=Path, help="local herdr checkout instead of GitHub")
    args = parser.parse_args()
    files = fetch_clone(args.commit, args.clone) if args.clone else fetch_github(args.commit)
    if not any(name.endswith(".toml") for name in files):
        sys.exit("no manifests found")
    TARGET.mkdir(parents=True, exist_ok=True)
    for stale in TARGET.glob("*.toml"):
        if stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (TARGET / name).write_bytes(content)
    (TARGET / "NOTICE").write_text(
        NOTICE.format(repo=REPO, manifest_dir=MANIFEST_DIR, commit=args.commit)
    )
    print(f"vendored {len(files) - 1} manifests from {REPO}@{args.commit[:12]} into {TARGET}")


if __name__ == "__main__":
    main()
