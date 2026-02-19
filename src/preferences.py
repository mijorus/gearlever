import gi
import threading
import logging
import os

from .lib.constants import FETCH_UPDATES_ARG
from .models.Models import InternalError
from .models.Settings import Settings
from .lib.utils import portal
from .lib.json_config import read_json_config, set_json_config
from .State import state
from dbus import Array as DBusArray
from .lib.terminal import sandbox_sh

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
            _('Show integrated AppImages outside the default folder'),
            'manage-files-outside-default-folder',
            _('List AppImages that have been integrated into the system menu but are located outside the default folder')
        )

        general_preference_group.add(self.default_location_row)
        general_preference_group.add(files_outside_folder_switch)

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
            state.set__('appimages-default-folder', file_path)
        else:
            raise InternalError(_('The folder must writeable'))

    def on_default_localtion_btn_clicked(self, widget):
        dialog = Gtk.FileDialog(title=_('Select a folder'), modal=True)

        dialog.select_folder(
            parent=self,
            cancellable=None,
            callback=self.on_select_default_location_response
        )

    def on_move_appimages_setting_changed(self, widget):
        self.settings.set_boolean('move-appimage-on-integration', self.move_to_destination_check.get_active())

    def create_boolean_settings_entry(self, label: str, key: str, subtitle: str = None) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=label, subtitle=subtitle)
        self.settings.bind(key, row, 'active', Gio.SettingsBindFlags.DEFAULT)

        return row
        
    def on_background_fetchupdates_changed(self, *args):
        key = 'fetch-updates-in-background'
        value: bool = self.settings.get_boolean(key)

        conf = read_json_config('settings')
        conf[key] = value

        set_json_config('settings', conf)
        
        inter = portal("org.freedesktop.portal.Background")
        res = inter.RequestBackground('', {
            'reason': 'Gear Lever background updates fetch', 
            'autostart': value, 
            'background': True, 
            'commandline': DBusArray(['gearlever', f'--{FETCH_UPDATES_ARG}'])
        })
