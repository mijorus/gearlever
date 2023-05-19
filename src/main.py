# main.py
#
# Copyright 2022 Lorenzo Paderi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from .lib.terminal import sh
from .lib.utils import log
from .providers.providers_list import providers
from .AboutDialog import AboutDialog
from .BoutiqueWindow import BoutiqueWindow
import sys
import gi
import logging
import subprocess

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw, Gdk, GLib # noqa

class BoutiqueApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(application_id='it.mijorus.boutique', flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.create_action('quit', self.quit, ['<primary>q'])
        self.create_action('about', self.on_about_action)
        self.create_action('preferences', self.on_preferences_action)
        self.create_action('open_file', self.on_open_file_chooser)
        self.create_action('open_log_file', self.on_open_log_file)
        self.win = None

    def do_startup(self):
        log('\n\n---- Application startup')
        Adw.Application.do_startup(self)

        css_provider = Gtk.CssProvider()
        css_provider.load_from_resource('/it/mijorus/boutique/assets/style.css')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        self.win = self.props.active_window

        if not self.win:
            self.win = BoutiqueWindow(application=self)

        self.win.present()

    def do_open(self, files: list[Gio.File], n_files: int, _):
        if files:
            for p, provider in providers.items():
                if provider.can_install_file(files[0]):
                    self.win = Adw.ApplicationWindow(application=self, visible=False)

                    dialog = provider.open_file_dialog(files[0], self.win)
                    dialog.connect('response', lambda w, _: self.win.close())
                    dialog.show()
                    break

        # for f in files:
        #     if isinstance(self.props.active_window, BoutiqueWindow):
        #         self.props.active_window.on_selected_local_file(f)
        #         break

    def on_about_action(self, widget, _):
        """Callback for the app.about action."""
        about = AboutDialog(self.props.active_window)
        about.present()

    def on_preferences_action(self, widget, _):
        """Callback for the app.preferences action."""
        print('app.preferences action activated')

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
            activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def on_open_file_chooser(self, widget, _):
        if not self.win:
            return

        def on_open_file_chooser_reponse(widget, id):
            selected_file = widget.get_file()

            if selected_file and isinstance(self.props.active_window, BoutiqueWindow):
                self.props.active_window.on_selected_local_file(selected_file)

        self.file_chooser_dialog = Gtk.FileChooserNative(
            title='Open a file',
            action=Gtk.FileChooserAction.OPEN,
            transient_for=self.win
        )

        self.file_chooser_dialog.connect('response', on_open_file_chooser_reponse)
        self.file_chooser_dialog.show()

    def on_open_log_file(self, widget, _):
        if not self.win:
            return

        sh(['xdg-open',  GLib.get_user_cache_dir() + '/boutique.log'])


def main(version):
    """The application's entry point."""

    log_file = GLib.get_user_cache_dir() + '/boutique.log'
    print('Logging to file ' + log_file)

    app = BoutiqueApplication()
    logging.basicConfig(
        filename=log_file,
        filemode='a',
        encoding='utf-8',
        level=logging.DEBUG,
        force=True
    )

    return app.run(sys.argv)
