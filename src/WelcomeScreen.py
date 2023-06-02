from gi.repository import Gtk, Adw, GObject, Gio
from typing import Dict, List, Optional

from .State import state
from .lib.costants import APP_ID
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageListElement
from .models.AppListElement import AppListElement, InstalledStatus
from .models.Models import AppUpdateElement
from .components.FilterEntry import FilterEntry
from .components.CustomComponents import NoAppsFoundRow
from .components.AppListBoxItem import AppListBoxItem
from .preferences import Preferences
from .lib.utils import set_window_cursor, get_application_window

class WelcomeScreen(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_default_size(700, 700)
        self.set_resizable(False)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.carousel = Adw.Carousel()

        self.titlebar = Adw.HeaderBar(show_end_title_buttons=False)
        self.left_button = Gtk.Button(icon_name='go-previous', visible=True)
        self.right_button = Gtk.Button(label='Next', visible=True, css_classes=['suggested-action'])


        self.titlebar.set_title_widget(Gtk.Label(label='Tutorial'))
        self.titlebar.pack_start(self.left_button)
        self.titlebar.pack_end(self.right_button)
        
        self.set_titlebar(self.titlebar)

        first_page = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/tutorial/1.ui')
        [self.carousel.append(el.get_object('target')) for el in [first_page]]

        container.append(self.carousel)
        
        self.set_child(container)