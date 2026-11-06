"""Fork the OCA addons repositories into another organization."""

import time

import click
from github3.exceptions import GitHubError, NotFoundError

from . import github_login
from .config import NOT_ADDONS

SOURCE_ORG = "OCA"


def get_oca_repositories(github):
    return sorted(
        repo.name
        for repo in github.organization(SOURCE_ORG).repositories()
        if repo.name not in NOT_ADDONS and not repo.archived
    )


def branch_exists(repository, branch_name):
    try:
        repository.branch(branch_name)
    except NotFoundError:
        return False
    return True


def wait_for_branch(repository, branch_name, timeout, interval=5):
    """Forks are created asynchronously, wait until the branch is available."""
    deadline = time.monotonic() + timeout
    while not branch_exists(repository, branch_name):
        if time.monotonic() > deadline:
            return False
        time.sleep(interval)
    return True


@click.command()
@click.argument("org-name")
@click.option(
    "--repos",
    "repos",
    multiple=True,
    help="Repository to fork (can be repeated). Defaults to all OCA addons repos.",
)
@click.option(
    "--default-branch",
    "default_branch",
    help="Branch to set as default in the fork, if it exists in the OCA repo.",
)
@click.option(
    "--timeout",
    default=300,
    show_default=True,
    help="Seconds to wait for the fork to be ready before setting the default branch.",
)
def main(org_name, repos, default_branch, timeout):
    """Fork the OCA addons repositories into ORG_NAME organization."""
    github = github_login.login()
    failed = []
    for repo_name in repos or get_oca_repositories(github):
        if repo_name.startswith("l10n"):
            continue
        print("=" * 10, repo_name, "=" * 10)
        try:
            repository = github.repository(SOURCE_ORG, repo_name)
            new_fork = repository.create_fork(org_name)
            if not new_fork:
                raise RuntimeError("fork could not be created")
            print(f"Fork: {new_fork.html_url}")
            if not default_branch or new_fork.default_branch == default_branch:
                continue
            if not branch_exists(repository, default_branch):
                print(f"Branch {default_branch} not found in {SOURCE_ORG}, skipping")
                continue
            if not wait_for_branch(new_fork, default_branch, timeout):
                raise RuntimeError(
                    f"branch {default_branch} not available after {timeout}s"
                )
            new_fork.edit(name=new_fork.name, default_branch=default_branch)
            print(f"Default branch set to {default_branch}")
        except (GitHubError, RuntimeError) as exc:
            print(f"ERROR: {exc}")
            failed.append(repo_name)
    if failed:
        raise click.ClickException(f"Failed repositories: {', '.join(failed)}")


if __name__ == "__main__":
    main()
