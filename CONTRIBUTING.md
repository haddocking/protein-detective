# Contributing guidelines

We welcome any kind of contribution to our software, from simple comment or
question to a full fledged
[pull request](https://help.github.com/articles/about-pull-requests/). Please
read and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

A contribution can be one of the following cases:

1. you have a question;
1. you think you may have found a bug (including unexpected behavior);
1. you want to make some kind of change to the code base (e.g. to fix a bug, to
   add a new feature, to update documentation);
1. you want to make a new release of the code base.

The sections below outline the steps in each case.

## You have a question

1. use the search functionality of
   [ticket tracker](https://github.com/haddocking/protein-detective/issues) to
   see if someone already filed the same issue;
2. if your issue search did not yield any relevant results, make a new issue;
3. apply the "Question" label; apply other labels when relevant.

## You think you may have found a bug

1. use the search functionality of
   [ticket tracker](https://github.com/haddocking/protein-detective/issues) to
   see if someone already filed the same issue;
1. if your issue search did not yield any relevant results, make a new issue,
   making sure to provide enough information to the rest of the community to
   understand the cause and context of the problem. Depending on the issue, you
   may want to include:
   - the
     [SHA hashcode](https://help.github.com/articles/autolinked-references-and-urls/#commit-shas)
     of the commit that is causing your problem;
   - some identifying information (name and version number) for dependencies
     you're using;
   - information about the operating system;
1. apply relevant labels to the newly created issue.

## You want to make some kind of change to the code base

1. (**important**) announce your plan to the rest of the community _before you
   start working_. This announcement should be in the form of a (new) issue;
1. (**important**) wait until some kind of consensus is reached about your idea
   being a good idea;
1. if needed, fork the repository to your own Github profile and create your own
   feature branch off of the latest main commit. While working on your feature
   branch, make sure to stay up to date with the main branch by pulling in
   changes, possibly from the 'upstream' repository (follow the instructions at
   [Fork docs](https://help.github.com/articles/configuring-a-remote-for-a-fork/)
   and [Sync docs](https://help.github.com/articles/syncing-a-fork/));
1. clone the [protein-quest](https://github.com/haddocking/protein-quest)
   repository into the parent directory (one level up from protein-detective),
   since protein-detective depends on it during development:

   ```shell
   cd ..
   git clone git@github.com:haddocking/protein-quest.git
   cd protein-detective
   ```

   Since protein-quest is installed as a
   [source dependency](https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-sources),
   any changes you make to its code will be immediately available in
   protein-detective without needing to reinstall it.

1. install [uv](https://docs.astral.sh/uv) to manage this packages development
   environment);
1. Make sure `uv sync && . .venv/bin/activate && protein-detective --help`
   works;
1. make sure the existing tests still work by running `uv run pytest`;
1. add your own tests (if necessary);
1. format your code with `uvx ruff format` and sort imports with
   `uvx ruff check --select I --fix`;
1. lint your code with `uvx ruff check` (use `uvx ruff check --fix` to fix
   issues automatically);
1. type check your code with `uv run pyrefly check src tests`;
1. apply more formatting and linting with `uvx prek run --all-files`;
1. update or expand the documentation (see
   [Contributing with documentation](#contributing-with-documentation) section
   below);
1. [push](http://rogerdudler.github.io/git-guide/) your feature branch to (your
   fork of) the protein-detective repository on GitHub;
1. create the pull request, e.g. following the instructions at
   [Create Pull Request docs](https://help.github.com/articles/creating-a-pull-request/).

In case you feel like you've made a valuable contribution, but you don't know
how to write or run tests for it, or how to generate the documentation: don't
let this discourage you from making the pull request; we can help you! Just go
ahead and submit the pull request, but keep in mind that you might be asked to
append additional commits to your pull request.

## You want to make a new release of the code base

To create a release you need write permission on the repository.

1. Check the author list in [`CITATION.cff`](CITATION.cff)
1. Bump the version in
   [src/protein_detective/**version**.py](src/protein_detective/__version__.py).
1. Go to the
   [GitHub release page](https://github.com/haddocking/protein-detective/releases)
1. Press draft a new release button
1. Fill tag, title and description field. For tag use version from
   pyproject.toml and prepend with "v" character. For description use "Python
   package to detect proteins in EM density maps." line plus press "Generate
   release notes" button.
1. Press the Publish Release button
1. Wait until
   [Build and upload to PyPI](https://github.com/haddocking/protein-detective/actions/workflows/pypi-publish.yml)
   has completed
1. Verify new release is on
   [PyPi](https://pypi.org/project/protein-detective-em/#history)
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

## Automated code quality checks on git commit

This step is **optional** but recommended for developers who want to
automatically check code quality before committing.

We use [prek](https://github.com/j178/prek) to run pre-commit hooks. If you want
to set up automated checks:

1. Install prek if you haven't already:

   ```shell
   uv tool install prek
   ```

1. Install git hooks:

   ```shell
   prek install
   ```

1. Now every `git commit` will automatically run `prek run` on the files you're
   committing. The hooks will check for common issues like trailing whitespace,
   file endings, and run all configured linters.

1. If you ever want to disable the hooks, run:
   ```shell
   prek uninstall
   ```

## Are LLMs (Large Language Models) used or allowed to be used?

Yes, see [AIDECL.yaml](aidecl.yaml), just make sure a human always reviews the
output.
