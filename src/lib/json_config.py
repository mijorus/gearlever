import json
import gi
import os

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw, Gdk, GLib, GdkPixbuf  # noqa


def read_json_config(name: str):
    path = f'{GLib.get_user_config_dir()}/{name}.json'
    if not os.path.exists(path):
        return {}

    with open(path, 'r') as file:
        return json.loads(file.read())

def set_json_config(name: str, data):
    path = f'{GLib.get_user_config_dir()}/{name}.json'

    with open(path, 'w+') as file:
        file.write(json.dumps(data))