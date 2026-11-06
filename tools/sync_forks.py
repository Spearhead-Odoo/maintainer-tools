# License AGPLv3 (https://www.gnu.org/licenses/agpl-3.0-standalone.html)
"""Keep the forks of OCA repositories in another organization up to date.

Works on a directory holding clones of OCA repositories (e.g. created with
oca-clone-everything), one per subdirectory.
"""

from __future__ import annotations

import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import click

from .config import is_main_branch
from .github_login import get_token
from .oca_projects import url

GITHUB_OWNER_RE = re.compile(r"github\.com[:/]+([^/]+)/", re.IGNORECASE)

# flags of `git push --porcelain`
PUSHED, UP_TO_DATE, REJECTED, ERROR = "pushed", "up to date", "rejected", "error"
PUSH_FLAGS = {" ": PUSHED, "+": PUSHED, "*": PUSHED, "=": UP_TO_DATE, "!": REJECTED}


@dataclass
class RepoResult:
    name: str
    branches: dict[str, str] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def failed(self) -> bool:
        return bool(self.error) or any(
            state in (REJECTED, ERROR) for state in self.branches.values()
        )


def _git(path: Path, *args: str, check: bool = True, env=None):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def _clean(text: str) -> str:
    """Git message on a single line, without the 'hint:' lines."""
    lines = (line.strip() for line in text.splitlines())
    return " ".join(line for line in lines if line and not line.startswith("hint:"))


def _get_remotes(path: Path) -> dict[str, str]:
    """Return {remote name: url}, as configured (`git remote -v` applies
    url.<base>.insteadOf rewrites)."""
    proc = _git(path, "config", "--get-regexp", r"^remote\..*\.url$", check=False)
    remotes = {}
    for line in proc.stdout.splitlines():
        key, remote_url = line.split(maxsplit=1)
        remotes[key[len("remote.") : -len(".url")]] = remote_url
    return remotes


def _find_org_remote(path: Path, org: str) -> str | None:
    for name, remote_url in _get_remotes(path).items():
        match = GITHUB_OWNER_RE.search(remote_url)
        if match and match.group(1).lower() == org.lower():
            return name
    return None


def _get_repos(base_dir: Path, repos: str | None) -> list[Path]:
    if not repos or repos == ":all:":
        return sorted(p for p in base_dir.iterdir() if (p / ".git").exists())
    paths = [base_dir / repo.strip() for repo in repos.split(",")]
    for path in paths:
        if not (path / ".git").exists():
            raise click.BadParameter(f"{path} is not a git repository")
    return paths


def _token_env() -> dict[str, str] | None:
    """Environment making git authenticate on GitHub (https) with the token
    of oca-github-login, without exposing it in urls or arguments."""
    token = get_token()
    if not token:
        return None
    helper = (
        '!f() { test "$1" = get && echo username=x-access-token '
        '&& echo "password=$GIT_TOKEN"; }; f'
    )
    return {
        **os.environ,
        "GIT_TOKEN": token,
        # the empty helper resets any other configured helper
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "credential.https://github.com.helper",
        "GIT_CONFIG_VALUE_0": "",
        "GIT_CONFIG_KEY_1": "credential.https://github.com.helper",
        "GIT_CONFIG_VALUE_1": helper,
        "GIT_TERMINAL_PROMPT": "0",
    }


def _update_local_branch(path: Path, branch: str, ref: str, result: RepoResult):
    """Fast-forward the local branch to the upstream one."""
    current = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if current.stdout.strip() == branch:
        if _git(path, "status", "--porcelain", "--untracked-files=no").stdout:
            result.messages.append(
                f"{branch}: current branch has uncommitted changes, not updated"
            )
            return
        cmd = ["merge", "--ff-only", "--quiet", ref]
    else:
        cmd = ["fetch", "--quiet", ".", f"{ref}:refs/heads/{branch}"]
    proc = _git(path, *cmd, check=False)
    if proc.returncode:
        result.messages.append(
            f"{branch}: local branch can't be fast-forwarded ({_clean(proc.stderr)})"
        )


def _push_branch(path, remote, ref, branch, dry_run, env) -> tuple[str, str]:
    cmd = ["push", "--porcelain", remote, f"{ref}:refs/heads/{branch}"]
    if dry_run:
        cmd.insert(1, "--dry-run")
    proc = _git(path, *cmd, check=False, env=env)
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and line[0] in PUSH_FLAGS:
            state = PUSH_FLAGS[line[0]]
            return state, parts[2].strip() if state == REJECTED else ""
    return ERROR, _clean(proc.stderr)


def _sync_repo(path, upstream_org, remote, branches, dry_run, env) -> RepoResult:
    result = RepoResult(path.name)
    upstream = _find_org_remote(path, upstream_org)
    if not upstream:
        result.error = f"no remote pointing to {upstream_org}"
        return result
    if remote not in _get_remotes(path):
        result.error = f"remote '{remote}' not found, run set-remotes first"
        return result
    proc = _git(
        path,
        "fetch",
        "--prune",
        "--quiet",
        upstream,
        f"+refs/heads/*:refs/remotes/{upstream}/*",
        check=False,
    )
    if proc.returncode:
        result.error = f"fetch of '{upstream}' failed: {_clean(proc.stderr)}"
        return result
    upstream_branches = _git(
        path,
        "for-each-ref",
        "--format=%(refname:lstrip=3)",
        f"refs/remotes/{upstream}/",
    ).stdout.split()
    local_branches = _git(
        path, "for-each-ref", "--format=%(refname:short)", "refs/heads/"
    ).stdout.split()
    if branches:
        missing = [b for b in branches if b not in upstream_branches]
        if missing:
            result.messages.append(f"not in {upstream_org}: {', '.join(missing)}")
        to_sync = [b for b in branches if b in upstream_branches]
    else:
        to_sync = sorted(b for b in upstream_branches if is_main_branch(b))
    for branch in to_sync:
        ref = f"refs/remotes/{upstream}/{branch}"
        if not dry_run and branch in local_branches:
            _update_local_branch(path, branch, ref, result)
        state, detail = _push_branch(path, remote, ref, branch, dry_run, env)
        result.branches[branch] = state
        if detail:
            result.messages.append(f"{branch}: push {state}: {detail}")
    return result


@click.group()
@click.option(
    "--base-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    show_default=True,
    help="Directory holding the clones of the repositories.",
)
@click.option(
    "--repos",
    help="Comma-separated list of repo names, or :all: (default).",
)
@click.option(
    "--org-name",
    default="Spearhead-Odoo",
    show_default=True,
    help="Organization holding the forks.",
)
@click.option(
    "--remote-name",
    default="spearhead",
    show_default=True,
    help="Name of the git remote pointing to the forks.",
)
@click.pass_context
def main(ctx, base_dir: Path, repos: str | None, org_name: str, remote_name: str):
    """Keep the forks of OCA repositories in another organization up to date."""
    ctx.obj = {
        "paths": _get_repos(base_dir, repos),
        "org_name": org_name,
        "remote_name": remote_name,
    }


@main.command("set-remotes")
@click.option("--git-protocol", default="https", show_default=True)
@click.option("--dry-run", is_flag=True)
@click.pass_obj
def set_remotes(obj, git_protocol: str, dry_run: bool):
    """Add or update the remote pointing to the forks in every repository."""
    remote = obj["remote_name"]
    for path in obj["paths"]:
        expected = url(path.name, protocol=git_protocol, org_name=obj["org_name"])
        current = _get_remotes(path).get(remote)
        if current == expected:
            continue
        if current:
            print(f"{path.name}: {remote} {current} -> {expected}")
            cmd = ["remote", "set-url", remote, expected]
        else:
            print(f"{path.name}: add {remote} {expected}")
            cmd = ["remote", "add", remote, expected]
        if not dry_run:
            _git(path, *cmd)


@main.command()
@click.option(
    "--upstream-org",
    default="OCA",
    show_default=True,
    help="Organization to sync from, its remote is detected by url.",
)
@click.option(
    "--branches",
    help="Comma-separated list of branches (default: all the main branches).",
)
@click.option("--jobs", type=click.IntRange(1), default=4, show_default=True)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Fetch upstream but don't touch local branches and push with --dry-run.",
)
@click.pass_obj
def sync(obj, upstream_org: str, branches: str | None, jobs: int, dry_run: bool):
    """Fetch the upstream remote, fast-forward the local branches and push
    them to the forks.

    On https remotes the push uses the token of oca-github-login, if any.
    """
    branch_list = [b.strip() for b in branches.split(",")] if branches else []
    env = _token_env()
    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(
                _sync_repo,
                path,
                upstream_org,
                obj["remote_name"],
                branch_list,
                dry_run,
                env,
            ): path
            for path in obj["paths"]
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                result = RepoResult(futures[future].name, error=str(e))
            results.append(result)
            if result.failed:
                status = click.style("FAIL", fg="red")
            else:
                status = click.style("OK", fg="green")
            pushed = [b for b, s in result.branches.items() if s == PUSHED]
            print(
                f"{status} {result.name}"
                + (f" (pushed: {', '.join(pushed)})" if pushed else "")
            )
            for message in ([result.error] if result.error else []) + result.messages:
                print(f"    {message}")
    failed = [r.name for r in results if r.failed]
    pushed = sum(s == PUSHED for r in results for s in r.branches.values())
    print(f"\n{len(results)} repos, {pushed} branches pushed, {len(failed)} failed")
    if failed:
        raise SystemExit("Failed: " + ", ".join(sorted(failed)))


if __name__ == "__main__":
    main()
