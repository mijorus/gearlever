import time
import logging
import base64
import os
import shlex
from typing import Optional, Callable
from xml.sax.saxutils import escape
from gi.repository import Gtk, GObject, Adw, Gdk, Gio, Pango, GLib

from .State import state
from .models.AppListElement import InstalledStatus
from .providers.AppImageProvider import AppImageListElement, AppImageUpdateLogic
from .providers.providers_list import appimage_provider
from .lib.async_utils import _async, idle, debounce
from .lib.json_config import read_json_config, set_json_config
from .lib.utils import url_is_valid, get_file_hash, get_application_window
from .components.CustomComponents import CenteringBox, LabelStart
from .components.AppDetailsConflictModal import AppDetailsConflictModal


class MultiInstall(Gtk.ScrolledWindow):
    __gsignals__ = {
        "show-details": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self) -> None:
        super().__init__()
        self.ACTION_ROW_ICON_SIZE = 45

        self.app_list = []
        self.app_list_box = Gtk.ListBox(css_classes=['boxed-list'])

        install_all_btn = Gtk.Button(
            css_classes=['suggested-action'], label=_('Move all to the app menu'), halign=Gtk.Align.CENTER)
        
        install_all_btn.connect('clicked', self.on_install_all_clicked)

        self.main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, 
            margin_top=10, 
            margin_bottom=10, 
            margin_start=20, 
            margin_end=20,
            spacing=10
        )

        self.main_box.append(install_all_btn)
        self.main_box.append(self.app_list_box)

        self.set_child(self.main_box)

    def create_app_row(self, el: AppImageListElement):
        desc = escape(appimage_provider.get_description(el))
        row = Adw.ActionRow(
            title=el.name,
            subtitle=desc
        )

        icon = appimage_provider.get_icon(el)
        icon.set_pixel_size(self.ACTION_ROW_ICON_SIZE)
        
        details_btn = Gtk.Button(icon_name='gl-arrow2-top-right-symbolic',
                        valign=Gtk.Align.CENTER)
        details_btn.connect('clicked', self.on_details_btn_clicked, el)
        
        row.add_prefix(icon)
        row.add_suffix(details_btn)

        self.app_list.append(row)
        self.app_list_box.append(row)

    def on_details_btn_clicked(self, widget: Gtk.Button, el: AppImageListElement):
        self.emit('show-details', el)

    def set_from_local_files(self, files: list[Gio.File]):
        self.app_list_box.remove_all()
        self.app_list = []

        for f in files:
            el = appimage_provider.create_list_element_from_file(f)
            self.create_app_row(el)

        return True

    def on_install_all_clicked(self, widget: Gtk.Button):
        pass