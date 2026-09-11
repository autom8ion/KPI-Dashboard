"""Loads config/sources.yaml -- the single source of truth for which GitHub
org/repos this KPI dashboard watches. qa_collector's ingestion (`run.py`,
`db.py`), the demo seed script, and devlake/scripts/bootstrap.sh (via this
module's `--format shell` CLI, since that script is plain bash) all read
through here instead of hardcoding repo names -- see README.md "Plugging in
your own repos".
"""

from __future__ import annotations

import argparse
import pathlib
from dataclasses import dataclass

import yaml

CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


@dataclass
class RepoConfig:
    id: str
    org: str
    framework: str | None = None


@dataclass
class SourcesConfig:
    github_org: str
    repos: list[RepoConfig]

    def qa_collector_repos(self) -> dict[str, dict[str, str]]:
        """{repo_id: {"org": ..., "framework": ...}}, matching qa_collector.run's
        old hardcoded REPOS shape -- only repos with a framework set."""
        return {r.id: {"org": r.org, "framework": r.framework} for r in self.repos if r.framework}


def load(path: pathlib.Path = CONFIG_PATH) -> SourcesConfig:
    raw = yaml.safe_load(path.read_text())
    github_org = raw["github_org"]
    repos = [
        RepoConfig(id=r["id"], org=r.get("org", github_org), framework=r.get("framework"))
        for r in raw.get("repos", [])
    ]
    return SourcesConfig(github_org=github_org, repos=repos)


def _emit_shell(cfg: SourcesConfig) -> None:
    """Prints `GITHUB_ORG=...` / `REPOS=(...)` for devlake/scripts/bootstrap.sh
    to `eval`, since bash can't parse YAML on its own."""
    print(f'GITHUB_ORG="{cfg.github_org}"')
    print("REPOS=({})".format(" ".join(r.id for r in cfg.repos)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["shell"], default="shell")
    args = parser.parse_args()
    cfg = load()
    if args.format == "shell":
        _emit_shell(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
