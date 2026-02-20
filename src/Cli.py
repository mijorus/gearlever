import sys
import os

from .lib.constants import APP_ID
from gi.repository import Gtk, Gio, Adw, Gdk, GLib, GObject # noqa
from .BackgroudUpdatesFetcher import BackgroudUpdatesFetcher
from .lib.constants import FETCH_UPDATES_ARG
from .lib.utils import make_option, check_internet
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageUpdateLogic, AppImageListElement
from .lib.json_config import read_config_for_app, save_config_for_app, remove_update_config
from .models.UpdateManagerChecker import UpdateManagerChecker
from .models.UpdateManager import UpdateManager

class Cli():
    options = [
        make_option('integrate', description='Integrate an AppImage file'),
        make_option('update', description='Update an AppImage file'),
        make_option('remove', description='Trashes an AppImage, its .desktop file and icons  '),
        make_option('list-installed', description='List integrated apps'),
        make_option('list-updates', description='List available updates'),
        make_option('list-update-managers', description='List available update managers'),
        make_option('set-update-url', description='(DEPRECATED, use set-update-source instead) Set a custom update url'),
        make_option('set-update-source', description='Set a custom update source'),
        make_option(FETCH_UPDATES_ARG, description='Fetch updates in the background and sends a desktop notification, used on system startup'),
    ]

    @staticmethod
    def ask(message: str, options: list) -> str:
        _input = None

        message = message.strip() + ' '

        while not _input in options:
            _input = input(message)

        return _input

    @staticmethod
    def from_options(argv):
        if len(argv) < 2:
            return -1

        opt = Cli._get_invoked_option(argv)

        if opt:
            name = str(opt.long_name).replace('-', '_')
            getattr(Cli, name)(argv)
            sys.exit(0)


        if '--help' in argv:
            table = [[f'--{o.long_name}', o.description] for o in Cli.options]
            text = f'Usage: flatpak run {APP_ID} [OPTION...]'
            text += f'\nFor a better user experience, please set `alias gearlever=\'flatpak run {APP_ID}\'` in your .bashrc file'
            Cli._print_help_if_requested(argv, table, text)

        return -1

    @staticmethod
    def fetch_updates(argv):
        BackgroudUpdatesFetcher.fetch()

    @staticmethod
    def update(argv):
        Cli._print_help_if_requested(argv, [
            ['--yes | -y', 'Skips any interactive question'],
            ['--force', 'Forces updates for running applications'],
            ['--all', 'Updates all AppImages'],
        ], text='Usage: --update <file_path>')

        assume_yes = ('-y' in argv) or ('--yes' in argv)
        update_all = ('--all' in argv)
        force = ('--force' in argv)

        updates: list[AppImageListElement] = []

        if not check_internet():
            print('Internet connection not available')
            sys.exit(1)

        if update_all:
            Cli.list_updates([])
            
            if not assume_yes:
                ans = Cli.ask('\nDo you really want to update all AppImages? (y/N)', ['y', 'Y', 'n', 'N'])
                if ans.lower() != 'y':
                    sys.exit(0)

            assume_yes = True
            installed = appimage_provider.list_installed()
            
            for el in installed:
                manager = UpdateManagerChecker.check_url_for_app(el)

                if manager and manager.is_update_available(el):
                    updates.append(el)
        else:
            g_file = Cli._get_file_from_args(argv)
            el = Cli._get_list_element_from_gfile(g_file)
            updates = [el]

        if not updates:
            sys.exit(0)

        for el in updates:
            if appimage_provider.is_app_running(el) and (not force):
                print(f'{el.file_path} was skipped because the application is running; use --force to skip this check.')
                continue

            manager = UpdateManagerChecker.check_url_for_app(el)

            if not manager:
                print('No update method was found for this AppImage')
                sys.exit(0)

            if not assume_yes:
                ans = Cli.ask('Do you really want to update this AppImage? (y/N)', ['y', 'Y', 'n', 'N'])
                if ans.lower() != 'y':
                    sys.exit(0)

            print(f'Downloading update from: {manager.url}')
            appimage_provider.update_from_url(manager, el, 
                lambda s: print("\rStatus: " + str(round(s * 100)) + "%", end=""))

            print(f'\n{el.file_path} updated successfully')

    @staticmethod
    def remove(argv):
        Cli._print_help_if_requested(argv, [
            ['Usage: --remove <file_path>'],
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
            print(f'{el.file_path} was removed sucessfully')

    @staticmethod
    def set_update_url(argv):
        u_managers = ', '.join([n.name for n in UpdateManagerChecker.get_models()])

        Cli._print_help_if_requested(argv, [
            ['--manager <manager>', f'Optional: specify an update manager between: {u_managers}'],
            ['--unset', f'Unset a custom config for an app'],
        ], text='Deprecated (use --set-update-source), usage: --set-update-url <file_path> --url <url>')

        update_url = None
        update_url = Cli._get_arg_value(argv, '--url')
        manager_name = Cli._get_arg_value(argv, '--manager')

        if (not update_url):
            print('Error: "%s" is not a valid URL' % update_url)
            sys.exit(1)

        g_file = Cli._get_file_from_args(argv)
        el = appimage_provider.create_list_element_from_file(g_file)

        if '--unset' in argv:
            remove_update_config(el)
            sys.exit(0)

        selected_manager = None
        if manager_name:
            selected_manager = UpdateManagerChecker.get_model_by_name(manager_name)

        manager = UpdateManagerChecker.check_url(update_url, el, model=selected_manager)

        if manager:
            app_conf = read_config_for_app(el)
            app_conf['update_url'] = update_url
            app_conf['update_url_manager'] = manager.name
            save_config_for_app(app_conf)

            print(f'Saved update url for: {manager.name}')
        else:
            if selected_manager:
                print(f'The provided url is not supported by: {manager_name}')
            else:
                print(f'The provided url is not supported by any of the following providers: {u_managers}')
            sys.exit(1)

    @staticmethod
    def set_update_source(argv):
        u_managers = ', '.join([n.name for n in UpdateManagerChecker.get_models()])

        manager_name = Cli._get_arg_value(argv, '--manager')
        selected_model = None

        if manager_name:
            selected_model = UpdateManagerChecker.get_model_by_name(manager_name)
            manager: UpdateManager = selected_model(url='', embedded=False)
            Cli._print_help_if_requested(argv, [
                [f'--manager {manager_name}'],
                *[[f'OPTION {k}=<value>'] for k in manager.config.keys()]
            ], text='Usage: --set-update-source <file_path> --manager <manager> [...OPTIONS]')

        Cli._print_help_if_requested(argv, [
            ['--manager <manager>', f'Specify an update manager between: {u_managers}'],
            ['--unset', f'Unset a custom config for an app'],
        ], text='Usage: --set-update-source <file_path> --manager <manager> [...OPTIONS]')

        update_options = Cli._get_key_pairs(argv)

        if (not manager_name):
            print('Error: "%s" is not a valid update manager' % manager_name)
            sys.exit(1)

        g_file = Cli._get_file_from_args(argv)
        el = appimage_provider.create_list_element_from_file(g_file)

        if '--unset' in argv:
            remove_update_config(el)
            sys.exit(0)

        selected_model = None
        if manager_name:
            selected_model = UpdateManagerChecker.get_model_by_name(manager_name)

        if not selected_model:
            print('Error: "%s" is not a valid update manager' % manager_name)
            sys.exit(1)

        manager: UpdateManager = selected_model(url='', embedded=False, el=el)
        if set(manager.config.keys()) != set(update_options.keys()):
            print('Missing or invalid update configuration, required keys: ' + ', '.join(manager.config.keys()))
            sys.exit(1)

        manager_url = manager.get_url_from_params(**update_options)
        
        if not manager.can_handle_link(manager_url):
            print('Invalid configuration for ' + manager_name)
            sys.exit(1)

        boolean_vals = ['0', '1', 'false', 'true']
        for k, v in manager.config.items():
            if type(v) == bool:
                if update_options[k] not in boolean_vals:
                    print(f'{k} is not a boolean value, allowed values: ' + '/'.join(boolean_vals))
                    sys.exit(1)

                update_options[k] = (update_options[k] in ['1', 'true'])

        manager.config = update_options
        manager.set_url(manager_url)

        remove_update_config(el)

        app_conf = el.get_config()
        app_conf['update_url'] = manager.url
        app_conf['update_url_manager'] = manager.name
        app_conf['update_manager_config'] = manager.config
        save_config_for_app(app_conf)

        sys.exit(0)

    @staticmethod
    def integrate(argv):
        Cli._print_help_if_requested(argv, [
            ['--keep-both', 'If a name conflict occurs, keeps both files (default behaviour)'],
            ['--replace', 'If a name conflict occurs, replaces the old file with the one that you are currently integrating'],
            ['--yes | -y', 'Skips any interactive question and integrates the file'],
            ['--update-url <url>', 'Set a custom URL for updates'],
        ], text='Usage: --integrate <file_path>')

        g_file = Cli._get_file_from_args(argv)

        el = appimage_provider.create_list_element_from_file(g_file)
        if appimage_provider.is_installed(el):
            print('This AppImage is already integrated')
            sys.exit(0)

        el.update_logic = AppImageUpdateLogic.KEEP
        appimage_provider.refresh_data(el)

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
            ans = Cli.ask(f'\nDo you really want to integrate this AppImage? (y/N) ', ['y', 'Y', 'n', 'N'])

            if ans.lower() != 'y':
                sys.exit(0)

            if already_installed:
                ans = Cli.ask('\nAnother version of this app is already integrated.\nHow do you want to proceed? ((K)eep both/(R)eplace): ', 
                    ['k', 'r', 'K', 'R'])

            if ans.lower() == 'r':
                el.update_logic = AppImageUpdateLogic.REPLACE
                el.updating_from = already_installed

        appimage_provider.install_file(el)
        print(f'{el.file_path} was integrated successfully')

    @staticmethod
    def list_installed(argv):
        Cli._print_help_if_requested(argv, [
            ['-v', ' Show more info']
        ])

        apps = appimage_provider.list_installed()

        table = []
        for a in apps:
            app_conf = read_config_for_app(a)
            update_url = app_conf.get('update_url', None)
            manager = UpdateManagerChecker.check_url_for_app(a)
            update_mng = f'[{manager.name}]' if manager else '[UpdatesNotAvailable]'
            v = a.version or 'Not specified'
            table.append([a.name, f'[{v}]', update_mng, a.file_path])

        Cli._print_table(table)

    @staticmethod
    def list_updates(argv):
        Cli._print_help_if_requested(argv, [['-v', 'Prints update URL information']])

        installed = appimage_provider.list_installed()
        table = []

        if not check_internet():
            print('Internet connection not available')
            sys.exit(1)

        for el in installed:
            manager = UpdateManagerChecker.check_url_for_app(el)

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

    @staticmethod
    def list_update_managers(argv):
        models = UpdateManagerChecker.get_models()
        table = []

        for m in models:
            table.append([m.label, m.name])

        Cli._print_table(table)

    @staticmethod
    def _get_key_pairs(argv: list[str]) -> dict:
        result = {}
        for pair in argv:
            if '=' in pair:
                key, value = pair.split('=', 1)
                result[key] = value

        return result

    @staticmethod
    def _get_arg_value(argv: list[str], arg_name: str):
        if not arg_name in argv:
            return None

        i = argv.index(arg_name)

        if len(argv) < (i + 2):
            print(f'Error: {arg_name} requires a value')
            sys.exit(1)

        val = argv[i + 1]
        return val

    @staticmethod
    def _print_table(table):
        if (not table):
            return

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

    @staticmethod
    def _get_invoked_option(argv):
        for opt in Cli.options:
            long_name = str(opt.long_name)
            if f'--{long_name}' == argv[1]:
                return opt

        return None

    @staticmethod
    def _print_help_if_requested(argv, help: list, text=''):
        if '--help' in argv:
            opt = Cli._get_invoked_option(argv)
            if opt:
                print(str(opt.description))

            if text:
                print(text)

            Cli._print_table(help)
            print('\nMore documentation available at https://gearlever.mijorus.it')
            sys.exit(0)

    @staticmethod
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

    @staticmethod
    def _get_list_element_from_gfile(g_file: Gio.File):
        el = None

        for a in appimage_provider.list_installed():
            if a.file_path == g_file.get_path():
                el = a
                break

        if not el:
            print('Error: AppImage not integrated')
            sys.exit(1)
    
        return el
