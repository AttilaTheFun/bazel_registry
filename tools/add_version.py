#!/usr/bin/env python3
"""Adds a released version of a module to the registry, from its tag.

    tools/add_version.py <owner/repo> <tag> [--module NAME] [--version X.Y.Z]

Fetches GitHub's archive of the tag and writes modules/<name>/<version>/:
- source.json: the archive's url, its sha256 `integrity` and the
  `strip_prefix` it unpacks under;
- MODULE.bazel: the archive's own, byte for byte;
and lists the version in modules/<name>/metadata.json, making that file for
a module's first version.

The module's name and version are the tag's MODULE.bazel's own: its
`module()` must name the release's version (a tag v0.36.0 is version
0.36.0, the leading "v" dropped), or nothing is written. --module and
--version only say what to expect; they never override the file. A fork's
tag carries its upstream version with a suffix that sorts above it
(3.6.1.isomer.1 above 3.6.1), as the BCR's own patched versions do
(.bcr.1).

Then run tools/check_registry.py, as CI does, and open the pull request.
Standard library only.
"""

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch(url):
    with urllib.request.urlopen(url, timeout=300) as response:
        return response.read()


def module_version(text):
    """The name and version a MODULE.bazel's module() declares (as
    check_registry.py reads them)."""
    declaration = re.search(r"module\((.*?)\)", text, re.S)
    if not declaration:
        return None, None
    name = re.search(r'name\s*=\s*"([^"]+)"', declaration.group(1))
    version = re.search(r'version\s*=\s*"([^"]+)"', declaration.group(1))
    return (name.group(1) if name else None), (version.group(1) if version else None)


def version_key(version):
    """Orders versions as Bazel does closely enough for a listing: dotted
    parts, numbers by value, and a version below its own longer forms
    (3.6.1 < 3.6.1.isomer.1)."""
    release = version.split("-", 1)[0]
    return [(0, int(part), "") if part.isdigit() else (1, 0, part) for part in release.split(".")]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository", help="owner/repo on GitHub")
    parser.add_argument("tag", help="the release's tag, e.g. v0.36.0")
    parser.add_argument("--module", help="the module name to expect (default: the tag's MODULE.bazel's)")
    parser.add_argument("--version", help="the version to expect (default: the tag without a leading v)")
    args = parser.parse_args()

    url = f"https://github.com/{args.repository}/archive/refs/tags/{args.tag}.tar.gz"
    data = fetch(url)
    integrity = "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()

    # GitHub's archives hold one directory, <repo>-<tag less a leading v>;
    # read it rather than guess it.
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        tops = {name.split("/", 1)[0] for name in archive.getnames()}
        if len(tops) != 1:
            sys.exit(f"add_version.py: {url} unpacks to {len(tops)} directories, not one")
        prefix = tops.pop()
        found = archive.extractfile(f"{prefix}/MODULE.bazel") if f"{prefix}/MODULE.bazel" in archive.getnames() else None
        if found is None:
            sys.exit(f"add_version.py: {args.tag} has no MODULE.bazel at its root")
        module_file = found.read()

    name, version = module_version(module_file.decode())
    expected_version = args.version or (args.tag[1:] if args.tag.startswith("v") else args.tag)
    if not name or not version:
        sys.exit(f"add_version.py: {args.tag}'s MODULE.bazel declares no module() name and version")
    if args.module and name != args.module:
        sys.exit(f"add_version.py: {args.tag}'s MODULE.bazel names module {name}, not {args.module}")
    if version != expected_version:
        sys.exit(f"add_version.py: {args.tag}'s MODULE.bazel says version {version}, not {expected_version}: "
                 "a release's module() names its own version")

    module_dir = ROOT / "modules" / name
    version_dir = module_dir / version
    if version_dir.exists():
        sys.exit(f"add_version.py: {name}@{version} is already in the registry; a version is never replaced")
    version_dir.mkdir(parents=True)
    (version_dir / "MODULE.bazel").write_bytes(module_file)
    (version_dir / "source.json").write_text(json.dumps(
        {"url": url, "integrity": integrity, "strip_prefix": prefix}, indent=4) + "\n")

    metadata_file = module_dir / "metadata.json"
    metadata = json.loads(metadata_file.read_text()) if metadata_file.exists() else {
        "homepage": f"https://github.com/{args.repository}",
        "maintainers": [],
        "repository": [f"github:{args.repository}"],
        "versions": [],
        "yanked_versions": {},
    }
    metadata["versions"] = sorted(set(metadata["versions"]) | {version}, key=version_key)
    metadata_file.write_text(json.dumps(metadata, indent=4) + "\n")

    print(f"added {name}@{version} from {url}")
    print(f"  integrity {integrity}, strip_prefix {prefix}")
    print("next: python3 tools/check_registry.py")


if __name__ == "__main__":
    main()
