from gi.repository import Gtk, Adw, GObject, Gio
from typing import Dict, List, Optional

from .State import state
from .lib.costants import APP_ID
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageProvider
from .models.AppListElement import AppListElement, InstalledStatus
from .models.Models import AppUpdateElement
from .components.FilterEntry import FilterEntry
from .components.CustomComponents import NoAppsFoundRow
from .components.AppListBoxItem import AppListBoxItem
from .preferences import Preferences
from .lib.utils import get_element_without_overscroll, get_gsettings

class WelcomeScreen(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_default_size(700, 700)
        self.set_resizable(False)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.carousel = Adw.Carousel()
        self.carousel.connect('page-changed', self.on_page_chaged)

        self.titlebar = Adw.HeaderBar(show_end_title_buttons=False)
        self.left_button = Gtk.Button(icon_name='go-previous', visible=True, sensitive=False)
        self.right_button = Gtk.Button(label='Next', visible=True, css_classes=['suggested-action'])

        self.titlebar.set_title_widget(Gtk.Label(label='Tutorial'))
        self.titlebar.pack_start(self.left_button)
        self.titlebar.pack_end(self.right_button)
        
        self.set_titlebar(self.titlebar)

        first_page = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/tutorial/1.ui')
        second_page = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/tutorial/2.ui')
        third_page = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/tutorial/3.ui')
        last_page = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/tutorial/last.ui')

        pages = [el.get_object('target') for el in [first_page, second_page, third_page, last_page]]
        [self.carousel.append(el) for el in pages]

        location_label = second_page.get_object('location-label')
        location_label.set_label(location_label.get_label().replace('{location}', get_gsettings().get_string('appimages-default-folder')))
        last_page.get_object('close-window').connect('clicked', lambda w: self.close())

        self.left_button.connect('clicked', lambda w: self.carousel.scroll_to(get_element_without_overscroll(pages, int(self.carousel.get_position()) - 1), True))
        self.right_button.connect('clicked', lambda w: self.carousel.scroll_to(get_element_without_overscroll(pages, int(self.carousel.get_position()) + 1), True))

        container.append(self.carousel)
        
        self.set_child(container)

    def on_page_chaged(self, widget, index):
        self.left_button.set_sensitive(True)
        self.right_button.set_sensitive(True)

        if index == 0:
            self.left_button.set_sensitive(False)

        if index == (self.carousel.get_n_pages() - 1):
            self.right_button.set_sensitive(False)