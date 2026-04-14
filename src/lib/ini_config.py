import gi
import os
import configparser
import hashlib

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import GLib  # noqa


class Config():
    path = os.path.join(GLib.get_user_config_dir(), 'gearlever.conf')
    parser = configparser.ConfigParser()

    @staticmethod
    def exists():
        return os.path.exists(Config.path)

    @staticmethod
    def refresh():
        if Config.exists():
            Config.parser.read(Config.path)

    @staticmethod 
    def write():
        with open(Config.path, 'w') as f:
            Config.parser.write(f)

    @staticmethod
    def get_app_config(el, key, fallback=''):
        if not el.file_path:
            return None
        
        h = hashlib.md5(el.file_path.encode()).hexdigest()
        return Config.parser.get(f'app.{h}', key, fallback=fallback)
    
    @staticmethod
    def set_app_config(el, data: dict):
        if not el.file_path:
            return None
        
        h = hashlib.md5(el.file_path.encode()).hexdigest()
        data['name'] = el.name
        data['file_path'] = el.file_path
        Config.parser[f'app.{h}'] = data

    @staticmethod
    def get_app_update_config(el, key, fallback=''):
        if not el.file_path:
            return None

        h = hashlib.md5(el.file_path.encode()).hexdigest()
        return Config.parser.get(f'app.{h}.update_manager', key, fallback=fallback)

    @staticmethod
    def set_app_update_config(el, manager, data):
        if not el.file_path:
            return None

        h = hashlib.md5(el.file_path.encode()).hexdigest()
        Config.parser[f'app.{h}.update_manager'] = data
        Config.parser[f'app.{h}.update_manager']['manager'] = manager.name