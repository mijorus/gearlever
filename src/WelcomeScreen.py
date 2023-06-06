import logging
import os
from gi.repository import Gtk, Adw, GObject, Gio, GLib
from typing import Dict, List, Optional

from .lib.utils import get_element_without_overscroll, get_gsettings, gio_copy
from .lib.costants import APP_ID, APP_NAME

class WelcomeScreen(Gtk.Window):

    def __init__(self, pkgdatadir):
        super().__init__()
        self.set_default_size(700, 700)
        self.set_resizable(False)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.carousel = Adw.Carousel()
        self.carousel.connect('page-changed', self.on_page_changed)

        self.titlebar = Adw.HeaderBar(show_end_title_buttons=False)
        self.left_button = Gtk.Button(icon_name='go-previous', visible=True, sensitive=False)
        self.right_button = Gtk.Button(label='Next', visible=True, css_classes=['suggested-action'])

        self.titlebar.set_title_widget(Gtk.Label(label='Tutorial'))
        self.titlebar.pack_start(self.left_button)
        self.titlebar.pack_end(self.right_button)
        
        self.set_titlebar(self.titlebar)

        first_page = Gtk.Builder.new_from_resource(f'/it/mijorus/{APP_NAME}/gtk/tutorial/1.ui')
        second_page = Gtk.Builder.new_from_resource(f'/it/mijorus/{APP_NAME}/gtk/tutorial/2.ui')
        third_page = Gtk.Builder.new_from_resource(f'/it/mijorus/{APP_NAME}/gtk/tutorial/3.ui')
        last_page = Gtk.Builder.new_from_resource(f'/it/mijorus/{APP_NAME}/gtk/tutorial/last.ui')

        pages = [el.get_object('target') for el in [first_page, second_page, third_page, last_page]]
        [self.carousel.append(el) for el in pages]

        location_label = second_page.get_object('location-label')
        location_label.set_label(location_label.get_label().replace('{location}', get_gsettings().get_string('appimages-default-folder')))
        last_page.get_object('close-window').connect('clicked', lambda w: self.close())

        self.left_button.connect('clicked', lambda w: self.carousel.scroll_to(get_element_without_overscroll(pages, int(self.carousel.get_position()) - 1), True))
        self.right_button.connect('clicked', lambda w: self.carousel.scroll_to(get_element_without_overscroll(pages, int(self.carousel.get_position()) + 1), True))

        container.append(self.carousel)

        self.demo_folder = GLib.get_tmp_dir() + f'/{APP_ID}/demo'
        if not os.path.exists(self.demo_folder):
            os.makedirs(self.demo_folder)

        # move the demo appimage into a temp folder
        demo_app = Gio.File.new_for_path(f'{pkgdatadir}/{APP_NAME}/assets/demo.AppImage')
        gio_copy(demo_app, Gio.File.new_for_path(f'{self.demo_folder}/demo.AppImage'))

        logging.debug(f'Copied demo app into {self.demo_folder}')
        third_page.get_object('open-demo-folder').connect('clicked', self.on_open_demo_folder_clicked)

        self.set_child(container)


    def on_page_changed(self, widget, index):
        self.left_button.set_sensitive(True)
        self.right_button.set_sensitive(True)

        if index == 0:
            self.left_button.set_sensitive(False)

        if index == (self.carousel.get_n_pages() - 1):
            self.right_button.set_sensitive(False)

    def on_open_demo_folder_clicked(self, widget):
        gfile = Gio.File.new_for_path(self.demo_folder)
        launcher = Gtk.FileLauncher.new(gfile)
        launcher.launch()