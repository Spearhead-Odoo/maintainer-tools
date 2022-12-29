"""Create a fork in all addons project.
"""
import click

from . import github_login
from .oca_projects import OCA_PROJECTS


@click.command("Create an Fork to new Organization")
@click.argument("org-name")
@click.option(
    "--repos",
    "repos",
    multiple=True,
)
@click.option(
    "--default-branch",
    "default_branch",
)
def main(org_name, repos, default_branch=None):
    # Connect to GitHub
    github = github_login.login()
    all_projects = []
    for  oca_repos in OCA_PROJECTS.values():
        all_projects += oca_repos
    for repo_name in repos or all_projects:
        if repo_name.startswith("l10n"):
            continue
        print("=" * 10, repo_name, "=" * 10)
        repository = github.repository("OCA", repo_name)
        all_branches = []
        for branch in repository.branches():
            all_branches.append(branch.name)
        new_fork = repository.create_fork(org_name)
        if default_branch and default_branch in all_branches:
            new_fork.edit(name=repo_name, default_branch=default_branch)
        

if __name__ == '__main__':
   main()