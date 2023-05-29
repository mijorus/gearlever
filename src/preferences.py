import gi
import logging

from .models.Models import InternalError
from .lib.utils import get_gsettings
from .State import state

gi.require_version('Gtk', '4.0')

from gi.repository import Adw, Gtk, Gio, GLib  # noqa

class Preferences(Adw.PreferencesWindow):
    def __init__(self, **kwargs) :
        super().__init__(**kwargs)

        self.settings = get_gsettings()
 
        # page 1
        page1 = Adw.PreferencesPage()

        # general group
        general_preference_group = Adw.PreferencesGroup(name=_('General'))


        # default_location
        self.default_location_row = Adw.ActionRow(
            title=_('AppImage location'),
            subtitle=self.settings.get_string('appimages-default-folder')
        )

        pick_default_localtion_btn = Gtk.Button(icon_name='gearlever-file-manager-symbolic', valign=Gtk.Align.CENTER)
        pick_default_localtion_btn.connect('clicked', self.on_default_localtion_btn_clicked)
        self.default_location_row.add_suffix(pick_default_localtion_btn)
        general_preference_group.add(self.default_location_row)

        # move appimage on integration
        move_appimages_group = Adw.PreferencesGroup(name=_('File management'), title=_('File management'))
        move_appimages_row = Adw.ActionRow(
            title=_('Move AppImages into the destination folder'),
            subtitle=(_('Default behaviour'))
        )

        copy_appimages_row = Adw.ActionRow(
            title=_('Clone AppImages into the destination folder'),
            subtitle=(_('This option keeps the original file but doubles the disk usage'))
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

        self.move_to_destination_check.connect('toggled', self.on_move_appimages_setting_changed)
        self.copy_to_destination_check.connect('toggled', self.on_move_appimages_setting_changed)
        
        page1.add(general_preference_group)
        page1.add(move_appimages_group)
        self.add(page1)

    def on_select_default_location_response(self, dialog, result):
        try:
            selected_file = dialog.select_folder_finish(result)
        except Exception as e:
            logging.error(str(e))
            return

        if selected_file.query_exists() and selected_file.get_path().startswith(GLib.get_home_dir()):
            self.settings.set_string('appimages-default-folder', selected_file.get_path())
            self.default_location_row.set_subtitle(selected_file.get_path())
            state.set__('appimages-default-folder', selected_file.get_path())
        else:
            raise InternalError(_('The folder must be in your home directory'))

    def on_default_localtion_btn_clicked(self, widget):
        dialog = Gtk.FileDialog(title=_('Select a folder'), modal=True)

        dialog.select_folder(
            parent=self,
            cancellable=None,
            callback=self.on_select_default_location_response
        )

    def on_move_appimages_setting_changed(self, widget):
        self.settings.set_boolean('move-appimage-on-integration', self.move_to_destination_check.get_active())