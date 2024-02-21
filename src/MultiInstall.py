import time
import logging
import base64
import os
import shlex
from typing import Optional, Callable
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
    def __init__(self) -> None:
        super().__init__()

        self.app_list = []
        self.app_list_box = Gtk.ListBox(css_classes=['boxed-list'])

        install_all_btn = Gtk.Button(
            css_classes=['suggested-action'], label=_('Move all to the app menu'))
        
        install_all_btn.connect('clicked', self.on_install_all_clicked)

        self.main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, 
            margin_top=10, 
            margin_bottom=10, 
            margin_start=20, 
            margin_end=20
        )

        self.main_box.append(install_all_btn)
        self.main_box.append(self.app_list_box)

        self.set_child(self.main_box)

    def set_from_local_files(self, files: list[Gio.File]):
        print(files)

    def on_install_all_clicked(self, widget: Gtk.Button):
        pass