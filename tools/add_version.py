#!/usr/bin/env python3
"""Adds a released version of a module to the registry, from its tag.

    tools/add_version.py <owner/repo> <tag> [--module NAME] [--version X.Y.Z]
    tools/add_version.py <owner/repo> <tag or commit> --fork --version V [--patch FILE]...
    tools/add_version.py <owner/repo> v0.38.N --stamped

Fetches GitHub's archive of the tag and writes modules/<name>/<version>/:
- source.json: the archive's url, its sha256 `integrity` and the
  `strip_prefix` it unpacks under;
- MODULE.bazel: the archive's own, byte for byte;
and lists the version in modules/<name>/metadata.json, making that file for
a module's first version.

A release of our own: the module's name and version are the tag's
MODULE.bazel's own. Its `module()` must name the release's version (a tag
v0.36.0 is version 0.36.0, the leading "v" dropped), or nothing is written.
--module and --version only say what to expect.

A release stamped by CI (--stamped): from 0.38 a version is
MAJOR.MINOR.BUILD, and a repository commits MAJOR.MINOR.0 while CI stamps each
build's own (0.38.N). The tag v0.38.N's MODULE.bazel then says 0.38.0, and
the entry carries one patch (module_dot_bazel.patch) setting module()'s
version to the tag's, as a fork's entry does. Only that difference is
accepted: the tag's MAJOR.MINOR with BUILD 0.

A fork (--fork): a module this account carries changes to until upstream
takes them, from a commit or tag of the fork. --version names the entry, an
upstream version with a suffix that sorts above it (3.6.1.isomer.1 above
3.6.1), as the BCR's own patched versions do (.bcr.1). Each --patch is
applied to the archive in order (strip 1), then a last patch
(module_dot_bazel.patch) sets `module()`'s version to --version; the patches
go in the entry (patches/, listed in source.json with their hashes) and its
MODULE.bazel is the patched file. Patching uses the system's `patch`.

`include()` is for a root module only (or one overridden from a checkout), so
a registry's module can't have it. With --drop-includes the last patch also
removes the include() lines: only for files whose declarations are a
development module's own (dev_dependency = True, as rules_swift's example
modules are), which a module from a registry never reads anyway. Look at
what they declare before saying so.

A version, once added, is never replaced. Then run tools/check_registry.py,
as CI does, and open the pull request. Standard library only.
"""

import argparse
import base64
import difflib
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATCH = "module_dot_bazel.patch"


def fetch(url):
    with urllib.request.urlopen(url, timeout=300) as response:
        return response.read()


def sha256(data):
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()


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


def with_version(text, version):
    """The MODULE.bazel text with module()'s version set to `version`."""
    declaration = re.search(r"module\((.*?)\)", text, re.S)
    body = declaration.group(1)
    if re.search(r'version\s*=\s*"[^"]*"', body):
        body = re.sub(r'version\s*=\s*"[^"]*"', f'version = "{version}"', body, count=1)
    else:
        body = re.sub(r'(name\s*=\s*"[^"]+"\s*,?)', rf'\1\n    version = "{version}",', body, count=1)
    return text[:declaration.start(1)] + body + text[declaration.end(1):]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository", help="owner/repo on GitHub")
    parser.add_argument("ref", help="the release's tag (v0.36.0), or with --fork a tag or a full commit")
    parser.add_argument("--module", help="the module name to expect (default: the archive's MODULE.bazel's)")
    parser.add_argument("--version", help="the version to expect; with --fork, the entry's version")
    parser.add_argument("--fork", action="store_true", help="a fork's commit or tag: patched, its version set by --version")
    parser.add_argument("--stamped", action="store_true",
                        help="a release whose MODULE.bazel says MAJOR.MINOR.0 (CI stamps the build): the entry sets the tag's version")
    parser.add_argument("--patch", action="append", default=[], help="with --fork: a patch to apply (strip 1), in order")
    parser.add_argument("--drop-includes", action="store_true",
                        help="with --fork: remove MODULE.bazel's include() lines (their files must be dev-only)")
    args = parser.parse_args()
    if args.stamped and args.fork:
        sys.exit("add_version.py: --stamped is for a release of our own, --fork for a fork's commit")
    if (args.patch or args.drop_includes) and not args.fork:
        sys.exit("add_version.py: --patch and --drop-includes are for a fork's entry (--fork)")
    if args.fork and not args.version:
        sys.exit("add_version.py: a fork's entry needs --version")

    commit = re.fullmatch(r"[0-9a-f]{40}", args.ref) is not None
    if commit and not args.fork:
        sys.exit("add_version.py: a release is added from its tag; a commit only for a fork (--fork)")
    url = (f"https://github.com/{args.repository}/archive/{args.ref}.tar.gz" if commit
           else f"https://github.com/{args.repository}/archive/refs/tags/{args.ref}.tar.gz")
    data = fetch(url)

    with tempfile.TemporaryDirectory(prefix="add-version-") as work:
        # GitHub's archives hold one directory (<repo>-<tag less a leading
        # v>, or <repo>-<commit>); read it rather than guess it.
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            tops = {name.split("/", 1)[0] for name in archive.getnames()}
            if len(tops) != 1:
                sys.exit(f"add_version.py: {url} unpacks to {len(tops)} directories, not one")
            prefix = tops.pop()
            archive.extractall(work, filter="data")
        tree = Path(work) / prefix
        if not (tree / "MODULE.bazel").exists():
            sys.exit(f"add_version.py: {args.ref} has no MODULE.bazel at its root")
        original = (tree / "MODULE.bazel").read_bytes()
        name, declared = module_version(original.decode())
        if not name:
            sys.exit(f"add_version.py: {args.ref}'s MODULE.bazel declares no module() name")
        if args.module and name != args.module:
            sys.exit(f"add_version.py: {args.ref}'s MODULE.bazel names module {name}, not {args.module}")

        patches = []  # (file name, bytes), in the order they apply
        if args.fork:
            version = args.version
            for path in args.patch:
                body = Path(path).read_bytes()
                applied = subprocess.run(["patch", "-p1", "--forward", "--batch", "--silent"], input=body, cwd=tree,
                                         capture_output=True)
                if applied.returncode != 0:
                    sys.exit(f"add_version.py: {path} doesn't apply to {args.ref}:\n"
                             + applied.stdout.decode() + applied.stderr.decode())
                patches.append((Path(path).name, body))
            before = (tree / "MODULE.bazel").read_text()
            after = with_version(before, version)
            includes = re.findall(r'^include\(.*\)[ \t]*\n', after, re.M)
            if includes and not args.drop_includes:
                sys.exit(f"add_version.py: {args.ref}'s MODULE.bazel has include(), which a registry's module can't: "
                         "with --drop-includes they are removed (look first: their files must be dev-only)")
            for line in includes:
                print(f"dropping {line.strip()}")
                after = after.replace(line, "", 1)
            if after != before:
                diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                                    "a/MODULE.bazel", "b/MODULE.bazel"))
                patches.append((MODULE_PATCH, diff.encode()))
            module_file = after.encode()
        else:
            expected = args.version or (args.ref[1:] if args.ref.startswith("v") else args.ref)
            version = expected
            module_file = original
            if declared != expected:
                line = ".".join(expected.split(".")[:2] + ["0"])
                if not (args.stamped and declared == line):
                    sys.exit(f"add_version.py: {args.ref}'s MODULE.bazel says version {declared}, not {expected}: "
                             "a release's module() names its own version"
                             + ("" if args.stamped else f" (or, stamped by CI, {line}: --stamped)"))
                before = original.decode()
                after = with_version(before, version)
                diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                                    "a/MODULE.bazel", "b/MODULE.bazel"))
                patches.append((MODULE_PATCH, diff.encode()))
                module_file = after.encode()

    if len({file for file, _ in patches}) != len(patches):
        sys.exit("add_version.py: two patches share a file name")
    module_dir = ROOT / "modules" / name
    version_dir = module_dir / version
    if version_dir.exists():
        sys.exit(f"add_version.py: {name}@{version} is already in the registry; a version is never replaced")
    version_dir.mkdir(parents=True)
    (version_dir / "MODULE.bazel").write_bytes(module_file)
    source = {"url": url, "integrity": sha256(data), "strip_prefix": prefix}
    if patches:
        (version_dir / "patches").mkdir()
        for file, body in patches:
            (version_dir / "patches" / file).write_bytes(body)
        source["patches"] = {file: sha256(body) for file, body in patches}
        source["patch_strip"] = 1
    (version_dir / "source.json").write_text(json.dumps(source, indent=4) + "\n")

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
    print(f"  integrity {source['integrity']}, strip_prefix {prefix}"
          + (f", patches {', '.join(file for file, _ in patches)}" if patches else ""))
    print("next: python3 tools/check_registry.py")


if __name__ == "__main__":
    main()
