# Setup

## Requirements

* Python 3.11+
* uv: [https://docs.astral.sh/uv/getting-started/installation/](https://docs.astral.sh/uv/getting-started/installation/)

## Installation

Install project dependencies into a virtual environment:

```text
$ uv sync
```

Install the pre-commit hooks (run once per clone):

```text
$ uv run pre-commit install --install-hooks
```

# Development Tasks

Run the test suite:

```text
$ uv run pytest
```

Docstrings follow the NumPy convention, which Ruff's pydocstyle rules enforce. Run the full hook suite (Ruff format and
lint, mypy):

```text
$ uv run pre-commit run --all-files
```

# Commit Messages

Commits must follow [Conventional Commits](https://www.conventionalcommits.org); CI checks this with commitlint. The
commit type decides the next release:

| Type | Example | Release |
|------|---------|---------|
| `fix:` | `fix: handle missing zone list` | patch (0.16.0 → 0.16.1) |
| `feat:` | `feat: add surround AI` | minor (0.16.0 → 0.17.0) |
| `chore:`, `ci:`, `docs:`, `test:`, `refactor:` | `docs: update README` | none |

While the version is below 1.0, breaking changes (`feat!:` or a `BREAKING CHANGE:` footer) also bump the minor
version.

# Continuous Integration

Every pull request and every push to `aiomusiccast-co` runs pre-commit, commitlint and pytest on Python 3.11–3.14.

# Release Tasks

Releases are automatic. When a push to `aiomusiccast-co` passes CI and contains a `feat:` or `fix:` commit,
python-semantic-release:

1. bumps the version in `pyproject.toml`, `aiomusiccast_co/__init__.py` and `uv.lock`,
2. updates `CHANGELOG.md` and commits it as `chore(release): <version>`,
3. tags `v<version>` and creates the GitHub release,
4. publishes the build to PyPI as `aiomusiccast-co` (trusted publishing, no token).

Don't edit the version or `CHANGELOG.md` by hand, and don't create releases or tags manually.

To preview the next version locally:

```text
$ uvx --from python-semantic-release semantic-release --noop version --print
```
