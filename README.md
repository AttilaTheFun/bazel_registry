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
own `module()` must name the release's version (`v0.36.0` is `0.36.0`); a
fork's tag carries its upstream version with a suffix that sorts above it
(`3.6.1.isomer.1`), as the BCR's patched versions do (`.bcr.1`). A version,
once added, is never replaced.

CI (`tools/check_registry.py`) checks every version:
- its archive's hash matches `integrity`;
- its MODULE.bazel is the archive's own, naming the same version;
- `metadata.json` lists it.
