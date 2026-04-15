import logging
import json
import gi
import os
import configparser
import base64

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import GLib, GdkPixbuf  # noqa


def read_json_config(name: str):
    path = f'{GLib.get_user_config_dir()}/{name}.json'
    logging.debug(f'Reading config from {path}')

    if not os.path.isfile(path):
        return {}

    with open(path, 'r') as file:
        return json.loads(file.read() or '{}')

def read_config_for_app(el) -> dict:
    conf = read_json_config('apps')
    b64name = base64.b64encode(el.name.encode('utf8')).decode('ascii')

    app_config = conf[b64name] if b64name in conf else {}
    app_config['b64name'] = b64name

    return app_config
