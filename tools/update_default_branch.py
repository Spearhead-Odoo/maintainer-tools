"""Set the default branch of the repositories of an organization."""

import click
from github3.exceptions import GitHubError, NotFoundError

from . import github_login


@click.command()
@click.argument("org-name")
@click.option(
    "--default-branch",
    "default_branch",
    required=True,
    help="Branch to set as default, repos without it are skipped.",
)
@click.option(
    "--repos",
    "repos",
    multiple=True,
    help="Repository to update (can be repeated). Defaults to all repos of ORG_NAME.",
)
def main(org_name, default_branch, repos):
    """Set DEFAULT_BRANCH as default branch in the repositories of ORG_NAME."""
    github = github_login.login()
    if repos:
        repositories = (github.repository(org_name, name) for name in repos)
    else:
        repositories = github.organization(org_name).repositories(type="all")
    failed = []
    for repository in repositories:
        print("=" * 10, repository.name, "=" * 10)
        if repository.archived:
            print("Archived, skipping")
            continue
        if repository.default_branch == default_branch:
            print(f"Default branch is already {default_branch}")
            continue
        try:
            try:
                repository.branch(default_branch)
            except NotFoundError:
                print(f"Branch {default_branch} not found, skipping")
                continue
            repository.edit(name=repository.name, default_branch=default_branch)
            print(f"Default branch set to {default_branch}")
        except GitHubError as exc:
            print(f"ERROR: {exc}")
            failed.append(repository.name)
    if failed:
        raise click.ClickException(f"Failed repositories: {', '.join(failed)}")


if __name__ == "__main__":
    main()
