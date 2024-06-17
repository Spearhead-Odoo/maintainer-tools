"""Set default branch to repos.
"""
import click

from . import github_login
from .oca_projects import OCA_REPOSITORY_NAMES


@click.command("Set default branch to repos.")
@click.argument("org-name")
@click.option(
    "--default-branch",
    "default_branch",
    required=True,
)
@click.option(
    "--repos",
    "repos",
    multiple=True,
)
def main(org_name, default_branch, repos=None):
    # Connect to GitHub
    github = github_login.login()
    if not repos:
        repos = []
        org = github.organization(org_name)
        for repo in org.repositories(type="all"):
            repos.append(repo.name)
    for repo_name in repos:
        print("=" * 10, repo_name, "=" * 10)
        repository = github.repository(org_name, repo_name)
        all_branches = []
        for branch in repository.branches():
            all_branches.append(branch.name)
        if default_branch and default_branch in all_branches:
            repository.edit(name=repo_name, default_branch=default_branch)
        

if __name__ == '__main__':
   main()