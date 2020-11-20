#!/bin/sh -e
pipver="19.3.1"

if [ $# -eq 0 ]; then
  ve_dir=ve
else
  ve_dir="$1"
fi

if [ ! -d "$ve_dir" ]; then
  python3.6 -m venv "$ve_dir"
  "$ve_dir"/bin/pip install pip=="$pipver"
fi

# Pyright should be installed globally.
# Make sure your npm prefix is set correctly.
#
# https://docs.npmjs.com/resolving-eacces-permissions-errors-when-installing-packages-globally
npm install -g pyright@1.1.74

"$ve_dir"/bin/pip install -r dev-requirements.txt
