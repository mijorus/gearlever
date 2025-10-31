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

import sys
import gi
import logging
import shutil
import os

from .models.Settings import Settings
from .lib.terminal import sandbox_sh
from .lib.utils import make_option
from .lib.constants import APP_ID, APP_NAME, APP_DATA, TMP_DIR
from .providers.providers_list import appimage_provider
from .GearleverWindow import GearleverWindow
from  .WelcomeScreen import WelcomeScreen
from .preferences import Preferences
from .BackgroudUpdatesFetcher import BackgroudUpdatesFetcher
from  .Cli import Cli

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw, Gdk, GLib, GObject # noqa

LOG_FILE_MAX_N_LINES = 5000
LOG_FOLDER = os.path.join(GLib.get_user_cache_dir(), 'logs')
LOG_FILE = os.path.join(LOG_FOLDER, f'{APP_NAME}.log')

class GearleverApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self, version, pkgdatadir):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.create_action('about', self.on_about_action)
        self.create_action('preferences', self.on_preferences_action, ['<primary>comma'])
        self.create_action('open_log_file', self.on_open_log_file)
        self.create_action('open_welcome_screen', self.on_open_welcome_screen, ['F1'])
        self.win = None
        self.version = version
        self.add_main_option_entries(Cli.options)

    def do_handle_local_options(self, options):
        return -1

    def do_startup(self):
        logging.info(f'\n\n---- Application startup | version {self.version}')
        Adw.Application.do_startup(self)

        settings = Settings.settings

        logging.debug('::: Settings')
        for k in settings.props.settings_schema.list_keys():
            logging.debug(k + ': ' + str(settings.get_value(k)))

        logging.debug('::: End settings')

        css_provider = Gtk.CssProvider()
        css_provider.load_from_resource(f'/it/mijorus/{APP_NAME}/assets/style.css')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self, from_file=False):
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        self.win = self.props.active_window

        if not self.win:
            self.win = GearleverWindow(application=self, from_file=from_file)
            self.win.connect('close-request', self.on_close_request)

        print('Logging to file ' + LOG_FILE)
        self.win.present()

    def do_open(self, files: list[Gio.File], n_files: int, data):
        if not files:
            return

        for f in files:
            if not appimage_provider.can_install_file(f):
                return
        
        self.do_activate(from_file=True)
        self.win.on_selected_local_file(list(files))

    def on_about_action(self, widget, data):
        about = Adw.AboutDialog(
            application_name='Gear Lever',
            version=self.version,
            developers=['Lorenzo Paderi'],
            copyright='2024 Lorenzo Paderi',
            application_icon='it.mijorus.gearlever',
            issue_url='https://github.com/mijorus/gearlever',
        )

        about.set_translator_credits(_("translator_credits"))
        if self.win:
            about.present(self.win)

    def on_preferences_action(self, widget, _):
        """Callback for the app.preferences action."""
        pref = Preferences()
        pref.connect('close-request', lambda w: self.win.on_show_installed_list() if self.win else None)
        pref.present()

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

    def on_open_log_file(self, widget, event):
        if not self.win:
            return

        log_gfile = Gio.File.new_for_path(LOG_FOLDER)
        launcher = Gtk.FileLauncher.new(log_gfile)
        launcher.launch()

    def on_close_request(self, *args):
        if os.path.exists(TMP_DIR):
            shutil.rmtree(TMP_DIR)
        return False

    def on_open_welcome_screen(self, widget, event):
        tutorial = WelcomeScreen()
        if self.win:
            tutorial.present(self.win)

def main(version, pkgdatadir):
    """The application's entry point."""
    APP_DATA['PKGDATADIR'] = pkgdatadir

    LOG_FILE = os.path.join(LOG_FOLDER, f'{APP_NAME}.log')

    if not os.path.exists(LOG_FOLDER):
        os.makedirs(LOG_FOLDER)

    # Clear log file if it's too big
    log_file_size = 0
    if os.path.exists(LOG_FILE): 
        with open(LOG_FILE, 'r') as f:
            log_file_size = len(f.readlines())
        
        if log_file_size > LOG_FILE_MAX_N_LINES:
            with open(LOG_FILE, 'w+') as f:
                f.write('')

    logging.basicConfig(
        filename=LOG_FILE,
        filemode='a',
        encoding='utf-8',
        format='%(asctime)s %(levelname)-1s [%(filename)s:%(lineno)d] %(message)s',
        level= logging.DEBUG if Settings.settings.get_boolean('debug-logs') else logging.INFO,
        force=True
    )

    if len(sys.argv) > 1:
        Cli.from_options(sys.argv)

    app = GearleverApplication(version, pkgdatadir)
    app.run(sys.argv)
