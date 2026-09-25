# GitHub Workflow

The repository includes a basic GitHub Actions workflow that:

1. checks out the repository;
2. installs `uv`;
3. installs Python 3.12;
4. syncs project dependencies;
5. runs `pytest`.

This supports the DevOps goal of checking that the project still works after changes are committed.
