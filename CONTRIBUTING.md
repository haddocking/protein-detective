# Contributing guidelines

We welcome any kind of contribution to our software, from simple comment or question to a full fledged [pull request](https://help.github.com/articles/about-pull-requests/). Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

A contribution can be one of the following cases:

1. you have a question;
1. you think you may have found a bug (including unexpected behavior);
1. you want to make some kind of change to the code base (e.g. to fix a bug, to add a new feature, to update documentation);
1. you want to make a new release of the code base.

The sections below outline the steps in each case.

## You have a question

1. use the search functionality [here](https://github.com/haddocking/protein-detective/issues) to see if someone already filed the same issue;
2. if your issue search did not yield any relevant results, make a new issue;
3. apply the "Question" label; apply other labels when relevant.

## You think you may have found a bug

1. use the search functionality [here](https://github.com/haddocking/protein-detective/issues) to see if someone already filed the same issue;
1. if your issue search did not yield any relevant results, make a new issue, making sure to provide enough information to the rest of the community to understand the cause and context of the problem. Depending on the issue, you may want to include:
    - the [SHA hashcode](https://help.github.com/articles/autolinked-references-and-urls/#commit-shas) of the commit that is causing your problem;
    - some identifying information (name and version number) for dependencies you're using;
    - information about the operating system;
1. apply relevant labels to the newly created issue.

## You want to make some kind of change to the code base

1. (**important**) announce your plan to the rest of the community *before you start working*. This announcement should be in the form of a (new) issue;
1. (**important**) wait until some kind of consensus is reached about your idea being a good idea;
1. if needed, fork the repository to your own Github profile and create your own feature branch off of the latest main commit. While working on your feature branch, make sure to stay up to date with the main branch by pulling in changes, possibly from the 'upstream' repository (follow the instructions [here](https://help.github.com/articles/configuring-a-remote-for-a-fork/) and [here](https://help.github.com/articles/syncing-a-fork/));
1. install [uv](https://docs.astral.sh/uv) to manage this packages development environment);
1. Make sure `uv sync && . .venv/bin/activate && protein-detective --help` works;
1. make sure the existing tests still work by running `uv run pytest`;
1. add your own tests (if necessary);
1. format your code with `uvx ruff format` and sort imports with `uvx ruff check --select I --fix`;
1. lint your code with `uvx ruff check` (use `uvx ruff check --fix` to fix issues automatically);
1. type check your code with `uv run pyrefly check`;
1. update or expand the documentation (see [Contributing with documentation](#contributing-with-documentation) section below);
1. [push](http://rogerdudler.github.io/git-guide/) your feature branch to (your fork of) the protein-detective repository on GitHub;
1. create the pull request, e.g. following the instructions [here](https://help.github.com/articles/creating-a-pull-request/).

In case you feel like you've made a valuable contribution, but you don't know how to write or run tests for it, or how to generate the documentation: don't let this discourage you from making the pull request; we can help you! Just go ahead and submit the pull request, but keep in mind that you might be asked to append additional commits to your pull request.

## You want to make a new release of the code base

To create a release you need write permission on the repository.

1. Check the author list in [`CITATION.cff`](CITATION.cff)
1. Bump the version in [pyproject.toml](pyproject.toml).
1. Go to the [GitHub release page](https://github.com/haddocking/protein-detective/releases)
1. Press draft a new release button
1. Fill tag, title and description field. For tag use version from pyproject.toml and prepend with "v" character. For description use "Python package to detect proteins in EM density maps." line plus press "Generate release notes" button.
1. Press the Publish Release button
1. Wait until [Build and upload to PyPI](https://github.com/haddocking/protein-detective/actions/workflows/pypi-publish.yml) has completed
1. Verify new release is on [PyPi](https://pypi.org/project/protein-detective-em/#history)
1. Verify new Zenodo record has been created.

## Contributing with documentation

To work on notebooks in the docs/ directory:

```shell
uv sync --group docs
# Open a notebook with VS code and select .venv/bin/python as kernel
```

Start the live-reloading docs server with:

```shell
uv run mkdocs serve
```

Build the documentation site with:

```shell
uv run mkdocs build
# The site will be built in the `site/` directory.
# You can preview it with
python3 -m http.server -d site
```

<details>
<summary>Type checking notebooks</summary>

[Pyrefly](https://pyrefly.org/) does not support notebooks yet, so we need to convert them to python scripts and then run pyrefly on them.

```shell
uv run --group docs jupyter nbconvert --to python docs/*.ipynb
# Comment out magic commands
sed -i 's/^get_ipython/# get_ipython/' docs/*.py
uv run pyrefly check docs/*.py
rm docs/*.py
```

</details>
