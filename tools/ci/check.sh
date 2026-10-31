#!/bin/bash
# CI's check (tools/check_registry.py) in a container leased from the
# runner's OS Server, of Visor's agent image (Python 3 and `patch`, which the
# check uses, and the network it fetches each archive over): the runner's Mac
# lends the check a machine and runs nothing of it itself.
#
#   tools/ci/check.sh
#
#   REGISTRY_CI_IMAGE  the image (default: Visor's agent image, below)
#
# The committed tree goes in on the command's standard input (git archive)
# and the check runs where it lands: everything through `oss machine run
# container --inside` (as OS Server's own tools/ci/linux_build.sh), which
# holds a five-minute lease renewed while it runs and releases it however
# it ends: SIGTERM (the runner's cancel) releases it at once.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${REGISTRY_CI_IMAGE:-ghcr.io/attilathefun/visor-agent:0.41.2}"
OSS="/Applications/OS Server.app/Contents/Helpers/oss"
[ -x "$OSS" ] || OSS="$(command -v oss)"

# The check, in the container: the tree unpacked into /tmp/registry, then
# check_registry.py over it.
check='set -e
mkdir -p /tmp/registry && tar -x -C /tmp/registry && cd /tmp/registry
python3 --version
python3 tools/check_registry.py'

# The tree from a file, not a pipe: exec then makes oss this process, so the
# runner's cancel reaches it, and it releases the container. The file is in
# the job's own temporary folder, which the runner empties after the job.
tree="${RUNNER_TEMP:-$(mktemp -d)}/registry-tree.tar"
git -C "$ROOT" archive --format=tar -o "$tree" HEAD
exec "$OSS" machine run container --image="$IMAGE" --rosetta --cpus=6 --memory=8 --inside --workdir=/ -- sh -c "$check" < "$tree"
