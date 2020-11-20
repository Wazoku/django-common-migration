# django-common-migration

Find migrations in common between different versions of the code, for use with
reversing migrations on QA machines.

## Installation

Install the script via Pip.

`pip install django-commmon-migration`

You can then run it via Python:

`python -m common_migration --all-names foo,bar --app-name foo ~/old ~/new`

## Development

To set up the repository for development, first ensures that your global `npm`
prefix has been configured so you can install the correct version Pyright,
possibly by using `nvm`. See
[here](https://npm.github.io/installation-setup-docs/installing/a-note-on-permissions.html).

After your npm prefix is set, run `./initialize_repo.sh` to set everything up.

Run `ve/bin/tox` to run all of the tests for everything.
