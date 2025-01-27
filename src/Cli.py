import sys
import os

from gi.repository import Gtk, Gio, Adw, Gdk, GLib, GObject # noqa
from .BackgroudUpdatesFetcher import BackgroudUpdatesFetcher
from .lib.costants import FETCH_UPDATES_ARG
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageUpdateLogic
from .lib.json_config import read_config_for_app, read_json_config
from .models.UpdateManager import UpdateManagerChecker

class Cli():
    options = [
        (FETCH_UPDATES_ARG, 'Fetch updates'),
        ('integrate', 'Integrate an AppImage file'),
        ('uninstall', 'Trashes an AppImage file, its .desktop file and its icons; add --delete to remove the file completely'),
        ('list-installed', 'List integrated apps'),
        ('list-updates', 'List app updates'),
    ]

    def ask(message: str, options: list) -> str:
        _input = None

        while not _input in options:
            _input = input(message)

        return _input

    def from_options(options):
        for opt in Cli.options:
            if options.contains(opt[0]):
                name = opt[0].lower().replace('-', '_')
                getattr(Cli, name)(options)
                sys.exit(0)

        return -1

    def get_file_from_args(options):
        args = sys.argv[1:]

        for a in args:
            if not a.startswith('-'):
                g_file = Gio.File.new_for_path(a)

                if os.path.exists(g_file.get_path()):
                    return g_file

        return None

    def get_list_element_from_gfile(g_file: Gio.File):
        el = None

        for a in appimage_provider.list_installed():
            if a.file_path == g_file.get_path():
                el = a
                break

        if not el:
            raise Exception('File not installed')
    
        return el

    def fetch_updates(options):
        BackgroudUpdatesFetcher.fetch()

    def update(options):
        g_file = Cli.get_file_from_args(options)
        el = Cli.get_list_element_from_gfile(g_file)

        app_conf = read_config_for_app(el)
        update_url = app_conf.get('update_url', None)
        manager = UpdateManagerChecker.check_url(update_url, el)

        if not manager:
            print('No update method was found for this app')
            sys.exit(0)

        print(f'Downloading update from:\n{manager.url}')
        appimage_provider.update_from_url(manager, el, 
            lambda s: print("\rStatus: " + round(s) + "%", end=""))

        # print('Update completed')

    def uninstall(options):
        g_file = Cli.get_file_from_args(options)
        force = ('--delete' in sys.argv)

        if not g_file:
            sys.exit(1)

        el = Cli.get_list_element_from_gfile(g_file)
        appimage_provider.uninstall(el, force_delete=force)
        # print('Removed sucessfully')

    def integrate(options):
        g_file = Cli.get_file_from_args(options)

        if not g_file:
            sys.exit(1)

        el = appimage_provider.create_list_element_from_file(g_file)
        manager = UpdateManagerChecker.check_url(None, el)

        if not appimage_provider.can_install_file(g_file):
            print('This file format is not supported!')
            sys.exit(1)

        apps = appimage_provider.list_installed()

        already_installed = False
        for a in apps:
            if a.name == el.name:
                already_installed = True
                break

        if options.contains('--yes') == False \
            and options.contains('-y') == False:

            info_table = [
                ['Name', el.name,],
                ['Version', el.version or 'Not specified',],
                ['Description', el.description or 'None',],
                ['Update Source', 'None' if not manager else manager.name],
            ]

            Cli.print_table(info_table)
            ans = input('\nDo you really want to integrate this AppImage? (y/N) ')

            if ans.lower() != 'y':
                sys.exit(0)

            if already_installed:
                ans = Cli.ask('\nAnother version of this app is already integrated. How do you want to proceed? ((K)eep both/(R)eplace) ', 
                    ['k', 'r', 'K', 'R'])

            if ans.lower() == 'k':
                el.update_logic = AppImageUpdateLogic.KEEP
            elif ans.lower() == 'r':
                el.update_logic = AppImageUpdateLogic.REPLACE
        else:
            el.update_logic = AppImageUpdateLogic.KEEP
            
            if options.contains('--replace'):
                el.update_logic = AppImageUpdateLogic.REPLACE

        appimage_provider.install_file(el)
        print(f'{el.name} was integrated successfully')

    def list_installed(options):
        apps = appimage_provider.list_installed()

        table = []
        for a in apps:
            ps = os.path.split(a.file_path)
            file_name = ps[:-1]
            table.append([a.name, f'[{a.version}]', a.file_path])

        Cli.print_table(table)

    def list_updates(options):
        installed = appimage_provider.list_installed()
        table = []

        for el in installed:
            app_conf = read_config_for_app(el)
            update_url = app_conf.get('update_url', None)
            manager = UpdateManagerChecker.check_url(update_url, el)

            if not manager:
                continue

            try:
                if manager.is_update_available(el):
                    table.append([el.name, f'[Update available, {manager.name}]', update_url])
            except Exception as e:
                pass

        if not table:
            print('No updates available')
            return
        
        Cli.print_table(table)

    def print_table(table):
        longest_cols = [
            (max([len(str(row[i])) for row in table]) + 3)
            for i in range(len(table[0]))
        ]

        row_format = "".join(["{:<" + str(longest_col) + "}" for longest_col in longest_cols])
        for row in table:
            print(row_format.format(*row))