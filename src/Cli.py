import sys
import os

from gi.repository import Gtk, Gio, Adw, Gdk, GLib, GObject # noqa
from .BackgroudUpdatesFetcher import BackgroudUpdatesFetcher
from .lib.costants import FETCH_UPDATES_ARG
from .lib.utils import make_option
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageUpdateLogic
from .lib.json_config import read_config_for_app, read_json_config
from .models.UpdateManager import UpdateManagerChecker

class Cli():
    options = [
        make_option(FETCH_UPDATES_ARG, description='Fetch updates in the background and sends a desktop notification, used on system startup'),
        make_option('integrate', description='Integrate an AppImage file'),
        make_option('update', description='Update an AppImage file'),
        make_option('uninstall', description='Trashes an AppImage, its .desktop file and icons  '),
        make_option('list-installed', description='List integrated apps; add -v to show more update info'),
        make_option('list-updates', description='List available updates')
    ]

    def ask(message: str, options: list) -> str:
        _input = None

        message = message.strip() + ' '

        while not _input in options:
            _input = input(message)

        return _input

    def from_options(argv):
        if len(argv) < 2:
            return -1

        opt = Cli._get_invoked_option(argv)

        if opt:
            name = str(opt.long_name).replace('-', '_')
            getattr(Cli, name)(argv)
            sys.exit(0)

        return -1

    def fetch_updates(argv):
        BackgroudUpdatesFetcher.fetch()

    def update(argv):
        Cli._print_help_if_requested(argv, [
            ['Usage: --update <file_path>'],
            ['--yes | -y', 'Skips any interactive question'],
        ])

        assume_yes = ('-y' in argv) or ('--yes' in argv)

        g_file = Cli._get_file_from_args(argv)
        el = Cli._get_list_element_from_gfile(g_file)

        app_conf = read_config_for_app(el)
        update_url = app_conf.get('update_url', None)
        manager = UpdateManagerChecker.check_url(update_url, el)

        if not manager:
            print('No update method was found for this AppImage')
            sys.exit(0)

        if not assume_yes:
            ans = Cli.ask('Do you really want to update this AppImage? (y/N)', ['y', 'Y', 'n', 'N'])
            if ans.lower() != 'y':
                sys.exit(0)

        print(f'Downloading update from:\n{manager.url}')
        appimage_provider.update_from_url(manager, el, 
            lambda s: print("\rStatus: " + str(round(s * 100)) + "%", end=""))

        print(f'\n{el.file_path} updated successfully')

    def uninstall(argv):
        Cli._print_help_if_requested(argv, [
            ['Usage: --uninstall <file_path>'],
            ['--delete', 'Deletes the AppImage file from disk, instead of trashing it'],
            ['--yes | -y', 'Skips any interactive question'],
        ])

        g_file = Cli._get_file_from_args(argv)
        force = ('--delete' in argv)
        assume_yes = ('-y' in argv) or ('--yes' in argv)
        el = Cli._get_list_element_from_gfile(g_file)
        if not appimage_provider.is_installed(el):
            print('This AppImage is not integrated')
            sys.exit(1)

        q = 'Do you really want to delete this AppImage?'

        if force:
            q += ' This action is irreversible'

        ans = 'n'
        if not assume_yes:
            ans = Cli.ask(f'{q} (y/N)', ['y', 'Y', 'n', 'N'])

        if ans.lower() == 'y' or assume_yes:
            appimage_provider.uninstall(el, force_delete=force)
            print(f'{el.file_path} was uninstalled sucessfully')

    def integrate(argv):
        Cli._print_help_if_requested(argv, [
            ['Usage: --integrate <file_path>'],
            ['--keep-both', 'If a name conflict occurs, keeps both files (default behaviour)'],
            ['--replace', 'If a name conflict occurs, replaces the old file with the one that you are currently integrating'],
            ['--yes | -y', 'Skips any interactive question and integrates the file'],
        ])

        g_file = Cli._get_file_from_args(argv)

        el = appimage_provider.create_list_element_from_file(g_file)
        if appimage_provider.is_installed(el):
            print('This AppImage is already integrated')
            sys.exit(0)

        el.update_logic = AppImageUpdateLogic.KEEP
        appimage_provider.refresh_title(el)

        if '--replace' in argv:
            el.update_logic = AppImageUpdateLogic.REPLACE

        manager = UpdateManagerChecker.check_url(None, el)

        apps = appimage_provider.list_installed()

        already_installed = None
        for a in apps:
            if a.name == el.name:
                already_installed = a
                break

        if '--yes' not in argv \
            and '-y' not in argv:

            info_table = [
                ['Name', el.name,],
                ['Version', el.version or 'Not specified',],
                ['Description', el.description or 'None',],
                ['Update Source', 'None' if not manager else manager.name],
            ]

            Cli._print_table(info_table)
            ans = Cli.ask('\nDo you really want to integrate this AppImage? (y/N) ', ['y', 'Y', 'n', 'N'])

            if ans.lower() != 'y':
                sys.exit(0)

            if already_installed:
                ans = Cli.ask('\nAnother version of this app is already integrated.\nHow do you want to proceed? ((K)eep both/(R)eplace): ', 
                    ['k', 'r', 'K', 'R'])

            if ans.lower() == 'r':
                el.update_logic = AppImageUpdateLogic.REPLACE
                el.updating_from = already_installed

        appimage_provider.install_file(el)
        print(f'{el.name} was integrated successfully')

    def list_installed(argv):
        Cli._print_help_if_requested(argv, [])
        apps = appimage_provider.list_installed()

        table = []
        for a in apps:
            app_conf = read_config_for_app(a)
            update_url = app_conf.get('update_url', None)
            manager = UpdateManagerChecker.check_url(update_url, a)
            update_mng = f'[{manager.name}]' if manager else '[UpdatesNotAvailable]'
            table.append([a.name, f'[{a.version}]', update_mng, a.file_path])

        Cli._print_table(table)

    def list_updates(argv):
        Cli._print_help_if_requested(argv, [['-v', 'Prints update URL information']])

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
                    row = [el.name, f'[Update available, {manager.name}]', el.file_path]
                    if '-v' in argv:
                        row.append(manager.url)
                    
                    table.append(row)
            except Exception as e:
                pass

        if not table:
            print('No updates available')
            return

        Cli._print_table(table)

    def _print_table(table):
        longst_row = 0

        for r in table:
            if len(r) > longst_row:
                longst_row = len(r)

        
        for r in table:
            if len(r) < longst_row:
                while len(r) < longst_row:
                    r.append('')

        longest_cols = [
            (max([len(str(row[i])) for row in table]) + 3)
            for i in range(len(table[0]))
        ]

        row_format = "".join(["{:<" + str(longest_col) + "}" for longest_col in longest_cols])
        for row in table:
            print(row_format.format(*row))
    
    def _get_invoked_option(argv):
        for opt in Cli.options:
            long_name = str(opt.long_name)
            if f'--{long_name}' == argv[1]:
                return opt

        return None

    def _print_help_if_requested(argv, help: list[str]):
        if '--help' in argv:
            opt = Cli._get_invoked_option(argv)

            if opt:
                print(str(opt.description) + '\n')

            Cli._print_table(help)
            sys.exit(0)

    def _get_file_from_args(args):
        for a in args:
            if not a.startswith('-'):
                g_file = Gio.File.new_for_path(a)

                if os.path.exists(g_file.get_path()) \
                    and os.path.isfile(g_file.get_path()) \
                    and appimage_provider.can_install_file(g_file):
                    return g_file

        print('Error: please specify a valid AppImage file')
        sys.exit(1)

    def _get_list_element_from_gfile(g_file: Gio.File):
        el = None

        for a in appimage_provider.list_installed():
            if a.file_path == g_file.get_path():
                el = a
                break

        if not el:
            raise Exception('File not installed')
    
        return el
