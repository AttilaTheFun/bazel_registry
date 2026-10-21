# Bazel registry

A Bazel registry for this account's modules (Isomer, Visor and the forks
they need until upstream takes their changes), alongside the
[Bazel Central Registry](https://registry.bazel.build). Each version points
at a release's tag archive, with its hash.

To use it, list it before the BCR in `.bazelrc`:

```
common --registry=https://raw.githubusercontent.com/AttilaTheFun/bazel_registry/main
common --registry=https://bcr.bazel.build
```

Then depend on a module by version:

```starlark
bazel_dep(name = "isomer", version = "0.36.0")
```

## Layout

The [registry format](https://bazel.build/external/registry):

```
modules/<name>/metadata.json           the module's versions
modules/<name>/<version>/MODULE.bazel  that release's MODULE.bazel, unchanged
modules/<name>/<version>/source.json   its tag archive: url, integrity, strip_prefix
```

## Adding a version

A version is added only for a released tag, by a pull request, which the
code owner approves:

```
tools/add_version.py <owner/repo> <tag>      # e.g. AttilaTheFun/isomer v0.36.0
python3 tools/check_registry.py
```

`add_version.py` fetches the tag's archive and writes the version's
`source.json` and `MODULE.bazel` and its line in `metadata.json`. The tag's
own `module()` must name the release's version (`v0.36.0` is `0.36.0`). A
version, once added, is never replaced.

From 0.38 a version is MAJOR.MINOR.BUILD: a repository commits
MAJOR.MINOR.0 and CI stamps each build's own (0.38.N), so the tag v0.38.N's
`module()` says 0.38.0. Such a release is added with `--stamped`: the entry
carries one patch (`module_dot_bazel.patch`) setting `module()` to the tag's
version, and no other difference from the tag is accepted:

```
tools/add_version.py AttilaTheFun/isomer v0.38.4 --stamped
```

A fork this account carries changes to until upstream takes them is added
from a commit (or tag) of the fork, as a patched version that sorts above
upstream's (`3.6.1.isomer.1` above `3.6.1`), as the BCR's patched versions
are (`.bcr.1`):

```
tools/add_version.py AttilaTheFun/rules_swift <commit> --fork --version 3.6.1.isomer.1 \
    --patch <a.patch> --patch <b.patch> [--drop-includes]
```

The patches go in the entry (`patches/`, with their hashes in
`source.json`), the last one (`module_dot_bazel.patch`) setting `module()`'s
version; `--drop-includes` also removes `include()` lines, which only a root
module may have (for included files that declare only the fork's own
development dependencies).

CI (`tools/check_registry.py`) checks every version:
- its archive's hash matches `integrity`;
- its MODULE.bazel is the archive's own, naming the same version (for a
  fork's entry: its patches match their hashes, apply in order, and give
  that MODULE.bazel);
- `metadata.json` lists it.
