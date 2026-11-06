#!/usr/bin/env python3
"""Adds the published releases of this account's modules that the registry
hasn't got yet, each as tools/add_version.py adds one.

    tools/add_releases.py [--module NAME] [--tag TAG]

For each module it follows (FOLLOWED, or --module), lists the releases of
the repository its metadata.json names (GitHub's API: published ones, no
drafts or prereleases) and adds the newest, when it sorts above the
module's newest entry, with `tools/add_version.py <owner/repo> <tag>
--stamped`: the tag's MODULE.bazel names its own version or, stamped by CI,
MAJOR.MINOR.0. Only the newest: the registry has the versions someone asked
for, not every release since (two released between runs leave the older
out); --tag adds that one release, of any age.

GH_TOKEN (else GITHUB_TOKEN), when set, authenticates the API's requests.
Under GitHub Actions, when anything was added, it writes `title` (e.g.
"isomer 0.40.2") and `branch` (releases/isomer-0.40.2) to GITHUB_OUTPUT,
for the Releases workflow's pull request. Then run tools/check_registry.py,
as CI does. Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ beside the tools
from add_version import version_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# The modules whose releases are added as they are published: a release of
# our own, from its tag (not a fork's patched commit, which someone adds by
# hand with add_version.py --fork).
FOLLOWED = ["isomer"]


def releases(repository):
    """The repository's published releases' tags, newest first (GitHub's
    first hundred)."""
    request = urllib.request.Request(f"https://api.github.com/repos/{repository}/releases?per_page=100",
                                     headers={"Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        listed = json.load(response)
    return [release["tag_name"] for release in listed if not release["draft"] and not release["prerelease"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--module", help="only this module (default: every one FOLLOWED names)")
    parser.add_argument("--tag", help="with --module: only this release (e.g. v0.40.1), even one older than the newest entry")
    args = parser.parse_args()
    if args.tag and not args.module:
        sys.exit("add_releases.py: --tag is a release of --module's")

    added = []  # (module, version), in the order added
    for name in [args.module] if args.module else FOLLOWED:
        metadata_file = ROOT / "modules" / name / "metadata.json"
        if not metadata_file.exists():
            sys.exit(f"add_releases.py: the registry has no module {name}")
        metadata = json.loads(metadata_file.read_text())
        sources = [source for source in metadata.get("repository", []) if source.startswith("github:")]
        if not sources:
            sys.exit(f"add_releases.py: {name}'s metadata.json names no GitHub repository")
        repository = sources[0].removeprefix("github:")
        listed = set(metadata["versions"])
        newest = max(listed, key=version_key) if listed else None

        if args.tag:
            tag = args.tag
        else:
            tags = [tag for tag in releases(repository) if re.fullmatch(r"v?\d+(\.\d+)*", tag)]
            if not tags:
                print(f"{name}: {repository} has no published release")
                continue
            tag = max(tags, key=lambda tag: version_key(tag.removeprefix("v")))
        version = tag.removeprefix("v")
        if version in listed:
            print(f"{name}@{version} is in the registry already")
            continue
        if not args.tag and newest and version_key(version) <= version_key(newest):
            print(f"{name}: its newest release, {tag}, is older than the newest entry, {newest}")
            continue
        subprocess.run([sys.executable, str(ROOT / "tools" / "add_version.py"), repository, tag, "--stamped"], check=True)
        added.append((name, version))

    if added:
        title = ", ".join(f"{name} {version}" for name, version in added)
        branch = "releases/" + "_".join(f"{name}-{version}" for name, version in added)
        print(f"added: {title}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"title={title}\nbranch={branch}\n")


if __name__ == "__main__":
    main()
