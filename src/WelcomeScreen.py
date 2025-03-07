import logging
import os
from gi.repository import Gtk, Adw, GObject, Gio, GLib
from typing import Dict, List, Optional


from .State import state
from .lib.utils import get_element_without_overscroll, get_gsettings, gio_copy
from .lib.constants import APP_ID, APP_NAME, APP_DATA

class WelcomeScreen(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_default_size(700, 700)
        self.set_resizable(False)

        pkgdatadir = APP_DATA['PKGDATADIR']

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
        location_label.set_label(location_label.get_label().replace('{location}', '~/AppImages'))
        last_page.get_object('close-window').connect('clicked', lambda w: self.close())

        self.left_button.connect('clicked', lambda w: self.carousel.scroll_to(get_element_without_overscroll(pages, int(self.carousel.get_position()) - 1), True))
        self.right_button.connect('clicked', lambda w: self.carousel.scroll_to(get_element_without_overscroll(pages, int(self.carousel.get_position()) + 1), True))

        container.append(self.carousel)

        self.demo_folder = os.path.join(GLib.get_user_cache_dir(), APP_ID, 'demo')
        demo_app = Gio.File.new_for_path(os.path.join(pkgdatadir, APP_NAME, 'assets', 'demo.AppImage'))
        demo_app_dest = os.path.join(self.demo_folder, demo_app.get_basename())

        # if the demo file exists, the path to it exists so we can skip checking both
        if not os.path.exists(demo_app_dest):
            # create paths to demo file if the path does not exist
            os.makedirs(self.demo_folder, exist_ok=True)
            # move demo file to the demo_folder
            gio_copy(demo_app, Gio.File.new_for_path(demo_app_dest))
            logging.debug(f'Copied demo app into {self.demo_folder}')

        third_page.get_object('open-demo-folder').connect('clicked', self.on_open_demo_folder_clicked)
        second_page.get_object('open-preferences').connect('clicked', self.on_default_localtion_btn_clicked)

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

    def on_select_default_location_response(self, dialog, result):
        try:
            selected_file = dialog.select_folder_finish(result)
        except Exception as e:
            logging.error(str(e))
            return

        if selected_file.query_exists() and selected_file.get_path().startswith(GLib.get_home_dir()):
            get_gsettings().set_string('appimages-default-folder', selected_file.get_path())
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