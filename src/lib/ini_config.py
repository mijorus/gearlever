import gi
import os
import configparser
import hashlib
import logging

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
        logging.info(f'Writing config to {Config.path}')
        with open(Config.path, 'w') as f:
            Config.parser.write(f)

    @staticmethod
    def get_app_hash(el):
        return hashlib.md5(el.file_path.encode()).hexdigest()

    @staticmethod
    def get_app_config(el):
        h = Config.get_app_hash(el)
        k = f'app.{h}'

        if Config.parser.has_section(k):
            return dict(Config.parser[f'app.{h}'])
        return {}

    @staticmethod
    def delete_app_config(el):
        h = Config.get_app_hash(el)
        j = f'app.{h}'
        k = f'app.{h}.update_manager'

        for l in [j, k]:
            if Config.parser.has_section(l):
                logging.info(f'Deleting config section {l}')
                Config.parser.remove_section(l)

    @staticmethod
    def set_app_config(el, data: dict):
        h = Config.get_app_hash(el)
        logging.info(f'Setting app config for {el.name} (app.{h}): {data}')
        data['name'] = el.name
        data['file_path'] = el.file_path
        Config.parser[f'app.{h}'] = data

    @staticmethod
    def get_app_update_config(el):
        h = Config.get_app_hash(el)
        k = f'app.{h}.update_manager'

        if Config.parser.has_section(k):
            return dict(Config.parser[f'app.{h}.update_manager'])
        
        return {}

    @staticmethod
    def set_app_update_config(el, manager, data):
        h = Config.get_app_hash(el)
        logging.info(f'Setting update config for {el.name} (app.{h}.update_manager), manager={manager.name}: {data}')
        Config.parser[f'app.{h}.update_manager'] = data
        Config.parser[f'app.{h}.update_manager']['manager'] = manager.name

    @staticmethod
    def delete_app_update_config(el):
        h = Config.get_app_hash(el)
        k = f'app.{h}.update_manager'
        if Config.parser.has_section(k):
            logging.info(f'Deleting update config section {k}')
            Config.parser.remove_section(k)