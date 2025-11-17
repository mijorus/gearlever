import logging
from gi.repository import Gtk, GObject, Adw, Gdk, Gio, GLib

from .models.AppListElement import InstalledStatus
from .providers.AppImageProvider import AppImageListElement, AppImageUpdateLogic
from .providers.providers_list import appimage_provider
from .lib.async_utils import _async, idle, debounce
from .lib.utils import get_application_window
from .components.AppListBoxItem import AppListBoxItem

class MultiInstall(Gtk.ScrolledWindow):
    __gsignals__ = {
        "show-details": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
        "go-back": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (bool, )),
    }

    def __init__(self) -> None:
        super().__init__()
        self.ACTION_ROW_ICON_SIZE = 45

        self.app_list: list[AppImageListElement] = []
        self.app_list_box_items: list[AppListBoxItem] = []
        self.app_list_box = Gtk.ListBox(css_classes=['boxed-list'])

        self.install_all_btn = Gtk.Button(
            css_classes=['suggested-action'], label=_('Move all to the app menu'), halign=Gtk.Align.CENTER)
        
        self.install_all_btn.connect('clicked', self.on_install_all_clicked)

        self.main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, 
            margin_top=30, 
            margin_bottom=10, 
            margin_start=20, 
            margin_end=20,
            spacing=20
        )

        self.main_box.append(self.install_all_btn)
        self.main_box.append(self.app_list_box)

        self.already_installed_warn = Gtk.Button(
            css_classes=['flat'],
            visible=False,
            sensitive=False,
            halign=Gtk.Align.CENTER,
            child=Adw.ButtonContent(
                label=_('Some apps are already installed'),
                icon_name='gl-info-symbolic'
            )
        )

        self.main_box.append(self.already_installed_warn)

        clamp = Adw.Clamp(child=self.main_box)
        overlay = Gtk.Overlay(
            child=clamp,
        )


        self.progress_bar = Gtk.ProgressBar(
            css_classes=['osd', 'horizontal', 'top'], fraction=1
        )

        overlay.add_overlay(self.progress_bar)
        overlay.set_clip_overlay(self.progress_bar, True)

        self.set_child(overlay)

    @idle
    def create_app_row_complete_load(self, el: AppImageListElement, icon: Gtk.Image):
        row = AppListBoxItem(el, show_details_btn=True)
        row.set_icon(icon)

        if el.installed_status is InstalledStatus.INSTALLED:
            row.set_opacity(0.5)

        row.details_btn.connect('clicked', self.on_details_btn_clicked, el)

        self.app_list_box.append(row)
        self.app_list_box_items.append(row)

        fraction = len(self.app_list_box_items) / len(self.app_list)
        self.progress_bar.set_fraction(fraction)

        if fraction == 1:
            self.progress_bar.set_visible(False)

            not_installed_count = self.count_not_installed()

            self.install_all_btn.set_sensitive(not_installed_count > 0)

    def count_not_installed(self):
        not_installed_count = 0
        for el in self.app_list:
            if el.installed_status is InstalledStatus.NOT_INSTALLED:
                not_installed_count += 1

        return not_installed_count

    @_async
    def create_app_row(self, el: AppImageListElement):
        appimage_provider.refresh_data(el)
        icon = appimage_provider.get_icon(el)

        self.create_app_row_complete_load(el, icon)

    def show_confirmation_dialog(self):
        dialog = Adw.MessageDialog(
            transient_for=get_application_window(),
            heading=_('Do you really want to move all the apps to the menu?')
        )

        dialog.add_response('cancel', _('Cancel'))
        dialog.add_response('confirm', _('Proceed'))
        dialog.set_response_appearance('confirm', Adw.ResponseAppearance.SUGGESTED)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        checkbox = Gtk.CheckButton.new_with_label(_('I have verified the source of the apps'))
        checkbox.set_halign(Gtk.Align.CENTER)

        body.append(checkbox)
        dialog.set_extra_child(body)
        dialog.connect('response', self.on_dialog_response, checkbox)

        dialog.present()

    def on_dialog_response(self, dialog: Adw.MessageDialog, response: str, checkbox: Gtk.CheckButton):
        if not checkbox.get_active():
            return
        
        if response != 'confirm':
            return
        
        self.install_all_btn.set_sensitive(False)

        for el in self.app_list:
            if el.installed_status is InstalledStatus.INSTALLED:
                continue

            el.set_trusted()
            appimage_provider.install_file(el)

        self.emit('go-back', True)

    def on_details_btn_clicked(self, widget: Gtk.Button, el: AppImageListElement):
        self.emit('show-details', el)

    @_async
    def create_list_elements(self, files):
        for f in files:
            try:
                el = appimage_provider.create_list_element_from_file(f)
                el.update_logic = AppImageUpdateLogic.KEEP
                self.app_list.append(el)

            except Exception as e:
                logging.error(e)

        self.progress_bar.set_visible(True)
        for el in self.app_list:
            self.create_app_row(el)

        not_installed_count = self.count_not_installed()
        show_warn = not_installed_count != len(self.app_list)
        
        GLib.idle_add(lambda: 
            self.already_installed_warn.set_visible(show_warn))

    def set_from_local_files(self, files: list[Gio.File]):
        if self.progress_bar.get_fraction() not in [0, 1]:
            return True

        self.progress_bar.pulse()
        self.app_list_box.remove_all()
        self.app_list = []
        self.app_list_box_items = []

        self.install_all_btn.set_sensitive(False)

        installable = 0
        for f in files:
            if appimage_provider.can_install_file(f):
                installable += 1

        self.create_list_elements(files)
        return installable > 0

    def on_install_all_clicked(self, widget: Gtk.Button):
        body = Gtk.BaselinePosition
        self.show_confirmation_dialog()