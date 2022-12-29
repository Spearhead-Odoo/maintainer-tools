"""UPDATE all addons project.
"""
import collections , yaml

import click
import yaml
from yaml.loader import SafeLoader
from .oca_projects import url, _OCA_REPOSITORY_NAMES
from . import github_login
from giturlparse import parse as git_parse

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
        if not repo_info.get("remotes").get("origin"):
            print(f'Repositorio: {repo.name} NO TIENE un remote origin')
            continue
        print(f'Procesando Repositorio: {repo.name}')
        repo_tmp = repo.refresh()
        repo_origin = None
        # actualizar el remote origin para que sea el de la organizacion
        repo_url = git_parse(repo_info.get("remotes")["origin"])
        if repo_url.owner != org_name:
            repo_info["remotes"]["origin"] = url(repo.name, protocol="https", org_name=org_name)
        if repo_tmp.fork:
            repo_origin = repo_tmp.parent
            if "oca" not in repo_info.get("remotes"):
                fork_url = git_parse(repo_origin.html_url)
                if repo.name in _OCA_REPOSITORY_NAMES:
                    repo_info["remotes"]["oca"] = url(repo.name, protocol="https", org_name=fork_url.owner)
                elif repo_url.owner != org_name:
                    repo_info["remotes"]["oca"] = f'https://github.com/{repo_url.owner}/{repo.name}.git'
            
    with open(repos_yaml, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

if __name__ == '__main__':
   main()