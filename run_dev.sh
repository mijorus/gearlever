#!/usr/bin/env bash
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export GSETTINGS_SCHEMA_DIR="/var/lib/flatpak/app/it.mijorus.gearlever/current/active/files/share/glib-2.0/schemas:${GSETTINGS_SCHEMA_DIR}"
export PYTHONPATH="/var/lib/flatpak/app/it.mijorus.gearlever/current/active/files/lib/python3.13/site-packages:${REPO_DIR}:${REPO_DIR}/src:${PYTHONPATH}"

# If running in restricted or sandbox environment where ~/.config is read-only, use local dev config
if [ ! -w "${HOME}/.config" ]; then
    export XDG_CONFIG_HOME="${REPO_DIR}/.dev_config"
    mkdir -p "${XDG_CONFIG_HOME}"
fi

# Compile gresource if missing
if [ ! -f "${REPO_DIR}/src/gearlever.gresource" ]; then
    glib-compile-resources --sourcedir="${REPO_DIR}/src" "${REPO_DIR}/src/gearlever.gresource.xml" --target="${REPO_DIR}/src/gearlever.gresource"
fi

exec python3 -c "
import os, sys, signal, gettext, gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio
resource = Gio.Resource.load('${REPO_DIR}/src/gearlever.gresource')
resource._register()
gettext.install('gearlever')

from src import main
signal.signal(signal.SIGINT, signal.SIG_DFL)
sys.exit(main.main('4.6.2-dev', '${REPO_DIR}/src'))
" "$@"
