#!/usr/bin/env python3
"""Checks every version in the registry against its archive.

For each modules/<name>/<version>:
- source.json names an archive whose sha256 matches its `integrity`;
- MODULE.bazel is the archive's own (at `strip_prefix`) and names the module
  and this version; for an entry with patches (a fork's), each patch in
  patches/ matches its hash in source.json, they apply to the archive in
  order, and MODULE.bazel is the patched archive's;
- the module's metadata.json lists the version.

Exits 1 when anything does not match, saying what. Standard library only,
and the system's `patch` for patched entries.
"""

import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
problems = []


def problem(where, what):
    problems.append(f"{where}: {what}")


def archive_bytes(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def member(data, url, path):
    """The file at `path` inside the archive, or None."""
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                return archive.read(path)
            except KeyError:
                return None
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        try:
            found = archive.extractfile(path)
        except KeyError:
            return None
        return found.read() if found else None


def module_version(text):
    declaration = re.search(r"module\((.*?)\)", text, re.S)
    if not declaration:
        return None, None
    name = re.search(r'name\s*=\s*"([^"]+)"', declaration.group(1))
    version = re.search(r'version\s*=\s*"([^"]+)"', declaration.group(1))
    return (name.group(1) if name else None), (version.group(1) if version else None)


def check(module_dir, version_dir):
    where = f"{module_dir.name}@{version_dir.name}"
    source_file = version_dir / "source.json"
    module_file = version_dir / "MODULE.bazel"
    if not source_file.exists() or not module_file.exists():
        problem(where, "needs source.json and MODULE.bazel")
        return
    source = json.loads(source_file.read_text())
    url, integrity = source.get("url"), source.get("integrity", "")
    if not url or not integrity.startswith("sha256-"):
        problem(where, "source.json needs a url and a sha256 integrity")
        return
    data = archive_bytes(url)
    digest = "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()
    if digest != integrity:
        problem(where, f"the archive's hash is {digest}, not {integrity}")
    entry = module_file.read_text()
    name, version = module_version(entry)
    if name != module_dir.name or version != version_dir.name:
        problem(where, f"MODULE.bazel names {name}@{version}")
    prefix = source.get("strip_prefix", "")
    if not source.get("patches"):
        own = member(data, url, f"{prefix}/MODULE.bazel" if prefix else "MODULE.bazel")
        if own is None:
            problem(where, "the archive has no MODULE.bazel")
        elif own.decode() != entry:
            problem(where, "MODULE.bazel differs from the archive's")
        return
    patched = patched_module(where, version_dir, source, data, prefix)
    if patched is not None and patched != entry:
        problem(where, "MODULE.bazel differs from the patched archive's")


def patched_module(where, version_dir, source, data, prefix):
    """The archive's MODULE.bazel once the entry's patches are applied, in
    source.json's order, or None (with a problem said) when one is missing,
    has another hash, or doesn't apply."""
    with tempfile.TemporaryDirectory(prefix="check-registry-") as work:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(work, filter="data")
        tree = Path(work) / prefix if prefix else Path(work)
        for name, integrity in source["patches"].items():
            patch = version_dir / "patches" / name
            if not patch.exists():
                problem(where, f"patches/{name} is listed but missing")
                return None
            body = patch.read_bytes()
            digest = "sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode()
            if digest != integrity:
                problem(where, f"patches/{name}'s hash is {digest}, not {integrity}")
                return None
            applied = subprocess.run(["patch", f"-p{source.get('patch_strip', 0)}", "--forward", "--batch", "--silent"],
                                     input=body, cwd=tree, capture_output=True)
            if applied.returncode != 0:
                problem(where, f"patches/{name} doesn't apply: {(applied.stdout + applied.stderr).decode().strip()}")
                return None
        found = tree / "MODULE.bazel"
        if not found.exists():
            problem(where, "the patched archive has no MODULE.bazel")
            return None
        return found.read_text()


def main():
    for module_dir in sorted(p for p in (ROOT / "modules").iterdir() if p.is_dir()):
        metadata_file = module_dir / "metadata.json"
        listed = json.loads(metadata_file.read_text()).get("versions", []) if metadata_file.exists() else []
        if not metadata_file.exists():
            problem(module_dir.name, "needs metadata.json")
        for version_dir in sorted(p for p in module_dir.iterdir() if p.is_dir()):
            if version_dir.name not in listed:
                problem(f"{module_dir.name}@{version_dir.name}", "not in metadata.json's versions")
            check(module_dir, version_dir)
        for version in listed:
            if not (module_dir / version).is_dir():
                problem(f"{module_dir.name}@{version}", "listed in metadata.json but has no folder")
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        print("Every version matches its archive.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
