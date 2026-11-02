import gi
import threading
import logging
import os

from .lib.constants import FETCH_UPDATES_ARG
from .models.Models import InternalError
from .models.Settings import Settings
from .lib.utils import portal, show_message_dialog
from .lib.ini_config import Config
from dbus import Array as DBusArray

gi.require_version('Gtk', '4.0')

from gi.repository import Adw, Gtk, Gio, GLib  # noqa

class Preferences(Adw.PreferencesWindow):
    def __init__(self, **kwargs) :
        super().__init__(**kwargs)

        self.settings = Settings.settings

        # page 1
        page1 = Adw.PreferencesPage()

        # general group
        general_preference_group = Adw.PreferencesGroup(name=_('General'))


        # default_location
        self.default_location_row = Adw.ActionRow(
            title=_('AppImage default location'),
            subtitle=self.settings.get_string('appimages-default-folder')
        )

        pick_default_localtion_btn = Gtk.Button(icon_name='gearlever-file-manager-symbolic', valign=Gtk.Align.CENTER)
        pick_default_localtion_btn.connect('clicked', self.on_default_localtion_btn_clicked)
        self.default_location_row.add_suffix(pick_default_localtion_btn)

        files_outside_folder_switch = self.create_boolean_settings_entry(
            _('Show integrated AppImages outside the installation folders'),
            'manage-files-outside-default-folder',
            _('List AppImages that have been integrated into the system menu but are located outside your installation folders')
        )

        general_preference_group.add(self.default_location_row)
        general_preference_group.add(files_outside_folder_switch)

        # installation folders group
        install_folders_group = Adw.PreferencesGroup(
            name=_('Installation folders'),
            title=_('Installation folders'),
            description=_(
                'Besides the default location you can allow more folders, '
                'for example on another disk; you will be able to choose the destination when installing an app'
            )
        )

        self.extra_folder_rows: list[Adw.ActionRow] = []

        self.add_folder_row = Adw.ActionRow(
            title=_('Add a folder'),
            subtitle=_('Choose another location where new AppImages can be installed'),
        )

        add_folder_btn = Gtk.Button(
            icon_name='list-add-symbolic',
            valign=Gtk.Align.CENTER,
            css_classes=['flat'],
            tooltip_text=_('Add a folder'),
        )
        add_folder_btn.connect('clicked', self.on_add_folder_btn_clicked)
        self.add_folder_row.add_suffix(add_folder_btn)
        self.add_folder_row.add_prefix(Gtk.Image(icon_name='folder-download-symbolic', valign=Gtk.Align.CENTER))

        install_folders_group.add(self.add_folder_row)
        self.install_folders_group = install_folders_group

        self.rebuild_extra_folders_list()

        # updates management group
        updates_management_group = Adw.PreferencesGroup(name=_('Updates management'), title=_('Updates management'))
        autofetch_updates = self.create_boolean_settings_entry(
            _('Check updates on system startup'),
            'fetch-updates-in-background',
            _('Receive a notification when a new update is detected; updates will not be installed automatically')
        )

        updates_management_group.add(autofetch_updates)
        autofetch_updates.connect('notify::active', self.on_background_fetchupdates_changed)

        # file management group
        move_appimages_group = Adw.PreferencesGroup(name=_('File management'), title=_('File management'))
        move_appimages_row = Adw.ActionRow(
            title=_('Move AppImages into the destination folder'),
            subtitle=(_('Reduce disk usage'))
        )

        copy_appimages_row = Adw.ActionRow(
            title=_('Clone AppImages into the destination folder'),
            subtitle=(_('Keep the original file and create a copy in the destination folder'))
        )


        self.move_to_destination_check = Gtk.CheckButton(
            valign=Gtk.Align.CENTER,
            active=self.settings.get_boolean('move-appimage-on-integration')
        )

        self.copy_to_destination_check = Gtk.CheckButton(
            valign=Gtk.Align.CENTER,
            group=self.move_to_destination_check,
            active=(not self.settings.get_boolean('move-appimage-on-integration'))
        )

        move_appimages_row.add_prefix(self.move_to_destination_check)
        copy_appimages_row.add_prefix(self.copy_to_destination_check)

        move_appimages_group.add(move_appimages_row)
        move_appimages_group.add(copy_appimages_row)
        # move_appimages_group.add(exec_as_name_switch)

        self.move_to_destination_check.connect('toggled', self.on_move_appimages_setting_changed)
        self.copy_to_destination_check.connect('toggled', self.on_move_appimages_setting_changed)

        # naming conventions group
        nconvention_group = Adw.PreferencesGroup(name=_('Naming conventions'), title=_('Naming conventions'))
        exec_as_name_switch = self.create_boolean_settings_entry(
            _('Use executable name for integrated terminal apps'),
            'exec-as-name-for-terminal-apps',
            _('If enabled, apps that run in the terminal are renamed as their executable.\nYou would need to add the aforementioned folder to your $PATH manually.\n\nFor example, "golang_x86_64.appimage" will be saved as "go"')
        )

        nconvention_group.add(exec_as_name_switch)

        preview_minimal_ui = self.create_boolean_settings_entry(
            _('Preview new apps in a minimal UI'),
            'preview-minimal-ui',
        )
        
        block_appimage_extract = self.create_boolean_settings_entry(
            _('Use safe mechanisms to load metadata'),
            'block-unsafe-extractor',
            _('If enabled, the app will try to load an Appimage without using the built-in appimage-extract command.\nDisable only if you trust your sources: malicious apps could execute code when loading the metadata.')
        )

        general_preference_group.add(preview_minimal_ui)
        general_preference_group.add(block_appimage_extract)

        # debugging group
        debug_group = Adw.PreferencesGroup(name=_('Debugging'), title=_('Debugging'))
        debug_row = self.create_boolean_settings_entry(
            _('Enable debug logs'),
            'debug-logs',
            _('Increases log verbosity, occupying more disk space and potentially impacting performance.\nRequires a restart.')
        )

        debug_group.add(debug_row)

        page1.add(general_preference_group)
        page1.add(install_folders_group)
        page1.add(updates_management_group)
        page1.add(move_appimages_group)
        page1.add(nconvention_group)
        page1.add(debug_group)
        self.add(page1)

    def on_select_default_location_response(self, dialog, result):
        file_path = ''

        try:
            selected_file = dialog.select_folder_finish(result)
            file_path = selected_file.get_path()
        except Exception as e:
            logging.error(str(e))
            return

        if selected_file.query_exists() and os.access(file_path, os.W_OK):
            self.settings.set_string('appimages-default-folder', file_path)
            self.default_location_row.set_subtitle(file_path)
            self.rebuild_extra_folders_list()
        else:
            raise InternalError(_('The folder must writeable'))

    def on_default_localtion_btn_clicked(self, widget):
        dialog = Gtk.FileDialog(title=_('Select a folder'), modal=True)

        dialog.select_folder(
            parent=self,
            cancellable=None,
            callback=self.on_select_default_location_response
        )

    def rebuild_extra_folders_list(self, *args):
        for row in self.extra_folder_rows:
            self.install_folders_group.remove(row)

        self.extra_folder_rows = []
        known_folders = [os.path.expanduser(self.settings.get_string('appimages-default-folder'))]

        for folder in self.settings.get_strv('appimages-extra-folders'):
            path = os.path.expanduser(folder)

            if path in known_folders:
                continue

            known_folders.append(path)

            row = Adw.ActionRow(
                title=path,
                subtitle=_('Installation folder'),
            )

            remove_btn = Gtk.Button(
                icon_name='user-trash-symbolic',
                valign=Gtk.Align.CENTER,
                css_classes=['flat'],
                tooltip_text=_('Remove this folder from the list (the folder itself is not deleted)'),
            )
            remove_btn.connect('clicked', self.on_remove_extra_folder_clicked, path)
            row.add_suffix(remove_btn)

            self.install_folders_group.add(row)
            self.extra_folder_rows.append(row)

        # keep the "Add a folder" entry at the bottom of the group
        self.install_folders_group.remove(self.add_folder_row)
        self.install_folders_group.add(self.add_folder_row)

    def on_remove_extra_folder_clicked(self, widget, path: str):
        folders = [f for f in self.settings.get_strv('appimages-extra-folders')
                   if os.path.expanduser(f) != path]
        self.settings.set_strv('appimages-extra-folders', folders)
        self.rebuild_extra_folders_list()

    def on_add_folder_btn_clicked(self, widget):
        dialog = Gtk.FileDialog(title=_('Select a folder'), modal=True)

        dialog.select_folder(
            parent=self,
            cancellable=None,
            callback=self.on_add_folder_response
        )

    def on_add_folder_response(self, dialog, result):
        try:
            selected_file = dialog.select_folder_finish(result)
            file_path = selected_file.get_path()
        except Exception as e:
            logging.error(str(e))
            return

        if not file_path:
            return

        file_path = os.path.expanduser(file_path)

        if not (selected_file.query_exists() and os.path.isdir(file_path) and os.access(file_path, os.W_OK)):
            show_message_dialog(_('The folder must exist and be writable'))
            return

        known_folders = [os.path.expanduser(f) for f in self.settings.get_strv('appimages-extra-folders')]
        known_folders.append(os.path.expanduser(self.settings.get_string('appimages-default-folder')))

        if file_path in known_folders:
            show_message_dialog(_('This folder is already in the list'))
            return

        self.settings.set_strv(
            'appimages-extra-folders',
            [*self.settings.get_strv('appimages-extra-folders'), file_path]
        )
        self.rebuild_extra_folders_list()

    def on_move_appimages_setting_changed(self, widget):
        self.settings.set_boolean('move-appimage-on-integration', self.move_to_destination_check.get_active())

    def create_boolean_settings_entry(self, label: str, key: str, subtitle: str = None) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=label, subtitle=subtitle)
        self.settings.bind(key, row, 'active', Gio.SettingsBindFlags.DEFAULT)

        return row
        
    def on_background_fetchupdates_changed(self, *args):
        key = 'fetch-updates-in-background'
        value: bool = self.settings.get_boolean(key)

        Config.parser[Config.parser.default_section][key] = Config.return_boolean(value)
        Config.write()
        
        inter = portal("org.freedesktop.portal.Background")
        inter.RequestBackground('', {
            'reason': 'Gear Lever background updates fetch', 
            'autostart': value, 
            'background': True, 
            'commandline': DBusArray(['gearlever', f'--{FETCH_UPDATES_ARG}'])
        })
