#!/usr/bin/env python3
import os
import sys
import signal
import gettext
import warnings

# Suppress dbus syntax warnings on newer Python versions
warnings.filterwarnings("ignore", category=SyntaxWarning, module="dbus")

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(REPO_DIR, "src")

# Flatpak Python packages
FLATPAK_PACKAGES = "/var/lib/flatpak/app/it.mijorus.gearlever/current/active/files/lib/python3.13/site-packages"
if os.path.exists(FLATPAK_PACKAGES) and FLATPAK_PACKAGES not in sys.path:
    sys.path.insert(0, FLATPAK_PACKAGES)

if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# GSettings schema directory
FLATPAK_SCHEMA_DIR = "/var/lib/flatpak/app/it.mijorus.gearlever/current/active/files/share/glib-2.0/schemas"
if os.path.exists(FLATPAK_SCHEMA_DIR):
    current_schema_dir = os.environ.get("GSETTINGS_SCHEMA_DIR", "")
    os.environ["GSETTINGS_SCHEMA_DIR"] = f"{FLATPAK_SCHEMA_DIR}:{current_schema_dir}" if current_schema_dir else FLATPAK_SCHEMA_DIR

# Compile gresource if missing
gresource_file = os.path.join(SRC_DIR, "gearlever.gresource")
if not os.path.exists(gresource_file):
    import subprocess
    subprocess.run(["glib-compile-resources", "--sourcedir=" + SRC_DIR, os.path.join(SRC_DIR, "gearlever.gresource.xml"), "--target=" + gresource_file], check=True)

import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio
resource = Gio.Resource.load(gresource_file)
resource._register()
gettext.install("gearlever")

# Ensure argv[0] is clean for GApplication
sys.argv[0] = "gearlever"

from src import main

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.exit(main.main("4.6.2-dev", SRC_DIR))
