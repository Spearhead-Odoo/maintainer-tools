"""UPDATE all addons project.
"""
import collections , yaml

import click
import yaml
from yaml.loader import SafeLoader
from . import github_login

_mapping_tag = yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG

def dict_representer(dumper, data):
  return dumper.represent_mapping(_mapping_tag, data.iteritems())

def dict_constructor(loader, node):
  return collections.OrderedDict(loader.construct_pairs(node))

yaml.add_representer( collections.OrderedDict , dict_representer )
yaml.add_constructor( _mapping_tag, dict_constructor )


@click.command("Update all repositories")
@click.argument("org-name")
@click.option(
    "--repos_yaml",
    "repos_yaml",
)
@click.option(
    "--default-branch",
    "default_branch",
)
def main(org_name, repos_yaml, default_branch=None):
    with open(repos_yaml) as f:
        data = yaml.load(f, Loader=SafeLoader)
                    
    # Connect to GitHub
    github = github_login.login()
    org = github.organization(org_name)
    for repo in org.repositories(type="all"):
        if repo.name.startswith("l10n"):
            continue
        repo_info = data.get(f"./{repo.name}")
        if not repo_info:
            continue
        all_branches = []
        for branch in repo.branches():
            all_branches.append(branch.name)
        if default_branch not in all_branches:
            continue
        for indx, merge in enumerate(repo_info.get("merges")):
            if "origin " in merge:
                last_commit = repo.branch(default_branch).commit
                if merge == "origin $ODOO_VERSION":
                    continue
                repo_info.get("merges")[indx] = f"origin {last_commit.sha}"
                print(f'Repositorio: {repo.name}')
                print(f'Ultimo Commit: {last_commit.sha}')
    with open(repos_yaml, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

if __name__ == '__main__':
   main()