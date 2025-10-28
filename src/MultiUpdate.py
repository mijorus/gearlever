import logging
from gi.repository import Gtk, GObject, Adw, Gdk, Gio, GLib

from .models.AppListElement import InstalledStatus
from .providers.AppImageProvider import AppImageListElement, AppImageUpdateLogic
from .providers.providers_list import appimage_provider
from .lib.async_utils import _async, idle, debounce
from .lib.utils import get_application_window
from .models.UpdateManagerChecker import UpdateManagerChecker
from .components.AppListBoxItem import AppListBoxItem

class MultiUpdate(Gtk.ScrolledWindow):
    __gsignals__ = {
        "go-back": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (bool, )),
    }

    def __init__(self) -> None:
        super().__init__()
        self.ACTION_ROW_ICON_SIZE = 45

        self.app_list: list[AppImageListElement] = []
        self.app_list_box_items: list[AppListBoxItem] = []
        self.app_list_box = Gtk.ListBox(css_classes=['boxed-list'])
        self.current_update_manager = None
        self.green_light = True

        self.cancel_update_btn = Gtk.Button(
            label=_('Cancel update'), halign=Gtk.Align.CENTER)
        
        view_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, 
            spacing=10
        )

        main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, 
            margin_top=30, 
            margin_bottom=10, 
            margin_start=20, 
            margin_end=20,
            spacing=20
        )

        main_box.append(self.cancel_update_btn)
        main_box.append(self.app_list_box)

        clamp = Adw.Clamp(child=main_box)

        self.progress_bar = Gtk.ProgressBar(
            css_classes=['osd', 'horizontal', 'top'], fraction=1
        )

        view_box.append(self.progress_bar)
        view_box.append(clamp)

        self.cancel_update_btn.connect('clicked', self.on_cancel_update_btn)
        self.set_child(view_box)

    @idle
    def update_progress_fraction(self, p):
        self.progress_bar.set_fraction(p)

    def count_not_installed(self):
        not_installed_count = 0
        for el in self.app_list:
            if el.installed_status is InstalledStatus.NOT_INSTALLED:
                not_installed_count += 1

        return not_installed_count

    @idle
    def create_app_row(self, el: AppImageListElement):
        appimage_provider.refresh_title(el)
        icon = appimage_provider.get_icon(el)

        row = AppListBoxItem(el, show_details_btn=False)
        row.set_icon(icon)
        row.set_opacity(0.5)

        self.app_list_box.append(row)
        self.app_list_box_items.append(row)

    @idle
    def on_update_end(self):
        self.emit('go-back', None)

    @idle
    def mark_as_updated(self, el: AppImageListElement):
        for row in self.app_list_box_items:
            if row._app.file_path == el.file_path:
                row.set_opacity(1)
                return

    @_async
    def update_all(self):
        p = len(self.app_list)
        for i, el in enumerate(self.app_list):
            if not self.green_light:
                break

            manager = UpdateManagerChecker.check_url_for_app(el)
            self.current_update_manager = manager
            appimage_provider.update_from_url(manager, el, 
                status_cb=lambda s: self.update_progress_fraction((s / p) * (i + 1)))
            self.mark_as_updated(el)

        self.update_progress_fraction(1)
        self.on_update_end()

    def start(self):
        self.green_light = True
        self.progress_bar.set_fraction(0)
        self.app_list_box.remove_all()
        self.app_list = []
        self.app_list_box_items = []
        self.check_updatables()

    @_async
    def check_updatables(self):
        installed = appimage_provider.list_installed()

        for el in installed:
            manager = UpdateManagerChecker.check_url_for_app(el)
            if not manager:
                continue

            try:
                if manager.is_update_available(el):
                    self.app_list.append(el)
                    self.create_app_row(el)
            except Exception as e:
                pass

        self.update_all()

    def on_cancel_update_btn(self, button):
        self.green_light = False
        if self.current_update_manager:
            self.current_update_manager.cancel_download()