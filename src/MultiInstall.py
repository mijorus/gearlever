from typing import Optional, Callable
from xml.sax.saxutils import escape
from gi.repository import Gtk, GObject, Adw, Gdk, Gio, Pango, GLib


from .models.AppListElement import InstalledStatus
from .providers.AppImageProvider import AppImageListElement, AppImageUpdateLogic
from .providers.providers_list import appimage_provider
from .lib.async_utils import _async, idle, debounce
from .lib.json_config import read_json_config, set_json_config
from .lib.utils import url_is_valid, get_file_hash, get_application_window
from .components.AppListBoxItem import AppListBoxItem
from .components.AppDetailsConflictModal import AppDetailsConflictModal


class MultiInstall(Gtk.ScrolledWindow):
    __gsignals__ = {
        "show-details": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self) -> None:
        super().__init__()
        self.ACTION_ROW_ICON_SIZE = 45

        self.app_list: list[AppListBoxItem] = []
        self.app_list_box = Gtk.ListBox(css_classes=['boxed-list'])

        self.install_all_btn = Gtk.Button(
            css_classes=['suggested-action'], label=_('Move all to the app menu'), halign=Gtk.Align.CENTER)
        
        self.install_all_btn.connect('clicked', self.on_install_all_clicked)

        self.main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, 
            margin_top=10, 
            margin_bottom=10, 
            margin_start=20, 
            margin_end=20,
            spacing=10
        )

        self.main_box.append(self.install_all_btn)
        self.main_box.append(self.app_list_box)

        self.already_installed_warn = Gtk.Button(
            css_classes=['flat'],
            visible=True,
            sensitive=False,
            halign=Gtk.Align.CENTER,
            child=Adw.ButtonContent(
                label=_('Some apps are already installed'),
                icon_name='software-update-available-symbolic'
            )
        )

        self.main_box.append(self.already_installed_warn)

        clamp= Adw.Clamp(child=self.main_box)
        self.set_child(clamp)

    @idle
    def create_app_row_complete_load(self, el: AppImageListElement, icon: Gtk.Image):
        row = AppListBoxItem(el, show_details_btn=True)
        row.set_icon(icon)

        if el.installed_status is InstalledStatus.INSTALLED:
            row.set_opacity(0.5)

        row.details_btn.connect('clicked', self.on_details_btn_clicked, el)

        self.app_list.append(row)
        self.app_list_box.append(row)

    @_async
    def create_app_row(self, el: AppImageListElement):
        appimage_provider.refresh_title(el)
        icon = appimage_provider.get_icon(el)

        self.create_app_row_complete_load(el, icon)

    def show_confirmation_dialog(self):
        dialog = Adw.MessageDialog(
            parent=get_application_window(),
            heading=_('Do you really want to move all the apps to the menu?')
        )

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        checkbox = Gtk.CheckButton.new_with_label(_('I have verified the source of the apps'))
        checkbox.set_halign(Gtk.Align.CENTER)

        body.append(checkbox)
        dialog.set_extra_child(body)

        dialog.present()

    def on_details_btn_clicked(self, widget: Gtk.Button, el: AppImageListElement):
        self.emit('show-details', el)

    def set_from_local_files(self, files: list[Gio.File]):
        self.app_list_box.remove_all()
        self.app_list = []

        not_installed_count = 0

        for f in files:
            el = appimage_provider.create_list_element_from_file(f)
            self.create_app_row(el)

            if el.installed_status is InstalledStatus.NOT_INSTALLED:
                not_installed_count += 1

        self.install_all_btn.set_sensitive(not_installed_count > 0)
        self.already_installed_warn.set_visible(not_installed_count == 0)

        return True

    def on_install_all_clicked(self, widget: Gtk.Button):
        body = Gtk.BaselinePosition
        self.show_confirmation_dialog()