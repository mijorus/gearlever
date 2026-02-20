from gi.repository import Gtk, Adw, GObject, Gio, GLib
from typing import Dict, List, Optional

import logging

from .State import state
from time import sleep
from .lib.constants import APP_ID, ONE_UPDATE_AVAILABLE_LABEL, UPDATES_AVAILABLE_LABEL
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageListElement
from .models.AppListElement import InstalledStatus
from .components.FilterEntry import FilterEntry
from .components.CustomComponents import NoAppsFoundRow
from .components.AppListBoxItem import AppListBoxItem
from .preferences import Preferences
from .WelcomeScreen import WelcomeScreen
from .lib.utils import get_application_window, check_internet
from .lib.async_utils import _async, idle
from .models.UpdateManagerChecker import UpdateManagerChecker

fetch_updates_cache = None

class InstalledAppsList(Gtk.ScrolledWindow):
    __gsignals__ = {
        "selected-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
        "update-all": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    CHECK_FOR_UPDATES_LABEL = _('Check for updates')
    NO_UPDATES_FOUND_LABEL = _('No updates found')
    CHECKING_FOR_UPDATES_LABEL = _('Checking updates...')
    UPDATE_ALL_LABEL = _('Update all')

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp_size = 600

        self.container_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.updates_fetched = False

        self.installed_apps_list_slot = Gtk.Box()
        self.installed_apps_list = Gtk.ListBox(css_classes=["boxed-list"])
        self.installed_apps_list.connect('row-activated', self.on_activated_row)

        self.installed_apps_list_slot.append(self.installed_apps_list)

        self.installed_apps_list_rows: List[AppListBoxItem] = []
        self.no_apps_found_row = NoAppsFoundRow(visible=False)

        # Create the filter search bar
        self.filter_query: str = ''
        self.filter_entry = FilterEntry(_('Filter installed applications'), capture=get_application_window(), maximum_size=clamp_size)
        self.filter_entry.search_entry.connect('search-changed', self.trigger_filter_list)
        # self.filter_entry.set_search_mode(True)

        # title row
        title_row = Gtk.Box(margin_bottom=15, spacing=10)
        title_row.append( Gtk.Label(
            label=_('Installed applications'), 
            css_classes=['title-2'],
            hexpand=True,
            halign=Gtk.Align.START,
        ))

        # fetch updates btn
        self.updates_btn = Gtk.Button(
            label=self.CHECK_FOR_UPDATES_LABEL,
        )

        self.update_all_btn = Gtk.Button(
            label=self.UPDATE_ALL_LABEL,
            visible=False,
            css_classes=['suggested-action']
        )

        self.updates_btn.connect('clicked', self.on_fetch_updates_btn_clicked)
        self.update_all_btn.connect('clicked', self.on_update_all_btn_clicked)
        title_row.append(self.updates_btn)
        title_row.append(self.update_all_btn)

        [self.main_box.append(el) for el in [title_row, self.installed_apps_list_slot]]

        clamp = Adw.Clamp(child=self.main_box, maximum_size=clamp_size, margin_top=20, margin_bottom=20)

        self.clamp_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        [self.clamp_container.append(el) for el in [self.filter_entry, clamp]]

        # empty list placeholder
        builder = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/empty-list-placeholder.ui')
        self.placeholder = builder.get_object('target')
        builder.get_object('open-preferences').connect('clicked', self.open_preferences)
        builder.get_object('show-welcome-screen').connect('clicked', self.on_open_welcome_screen)

        self.container_stack.add_child(self.clamp_container)
        self.container_stack.add_child(self.placeholder)

        self.set_child(self.container_stack)
        state.connect__('appimages-default-folder', lambda k: self.refresh_list())

    # Emit and event that changes the active page of the Stack in the parent widget
    def on_activated_row(self, listbox, row: Gtk.ListBoxRow):
        self.filter_entry.set_search_mode(False)
        self.emit('selected-app', row._app)

    def trigger_search_mode(self):
        self.filter_entry.set_search_mode(
            not self.filter_entry.get_search_mode()
        )

    def refresh_list(self):
        self.installed_apps_list.remove_all()
        self.updates_btn.set_label(self.CHECK_FOR_UPDATES_LABEL)
        self.installed_apps_list_rows = []

        installed: List[AppImageListElement] = appimage_provider.list_installed()

        for i in installed:
            list_row = AppListBoxItem(i, activatable=True, selectable=False, hexpand=True)
            list_row.set_update_version(i.version, i.size)

            list_row.load_icon()
            self.installed_apps_list_rows.append(list_row)
            self.installed_apps_list.append(list_row)

        if installed:
            self.container_stack.set_visible_child(self.clamp_container)
        else:
            self.container_stack.set_visible_child(self.placeholder)

        self.installed_apps_list.append(self.no_apps_found_row)
        self.no_apps_found_row.set_visible(False)
        
        self.installed_apps_list.set_sort_func(lambda r1, r2: self.sort_installed_apps_list(r1, r2))
        self.installed_apps_list.invalidate_sort()

        self.update_all_btn.set_visible(False)

    @_async
    def fetch_updates(self, cache=False):
        global fetch_updates_cache

        if not check_internet():
            return

        logging.debug('Fetching for updates for all apps')

        if cache and fetch_updates_cache:
            logging.debug('Getting updates list from cache')

            self.complete_updates_fetch(
                fetch_updates_cache['updatable_filepaths'], 
                fetch_updates_cache['updatable_apps'], 
                fetch_updates_cache['updates_available']
            )

            return

        GLib.idle_add(lambda: self.updates_btn.set_label(self.CHECKING_FOR_UPDATES_LABEL))
        GLib.idle_add(lambda: self.updates_btn.set_sensitive(False))

        updatable_apps = 0
        updates_available = 0
        final_rows = []
        for row in self.installed_apps_list_rows:
            manager = UpdateManagerChecker.check_url_for_app(row._app)

            updatable_apps += 1
            if not manager:
                continue

            logging.debug(f'Found app with update url: {manager.url}')

            try:
                status = manager.is_update_available(row._app)

                if status:
                    updates_available += 1
                    final_rows.append(row)
            except Exception as e:
                logging.error(e)

        self.updates_fetched = True
        updatable_filepaths = [f._app.file_path for f in final_rows]
        fetch_updates_cache = {
            'updatable_filepaths': updatable_filepaths, 
            'updatable_apps': updatable_apps, 
            'updates_available': updates_available
        }

        sleep(1)
        self.complete_updates_fetch(updatable_filepaths, updatable_apps, updates_available)

    @idle
    def complete_updates_fetch(self, updatable_filepaths: list[str], updatable_apps: int, updates_available: int):
        for row in self.installed_apps_list_rows:
            if row._app.file_path in updatable_filepaths:
                row.show_updatable_badge()

        self.update_all_btn.set_visible(updates_available > 0)
        if updates_available == 0:
            self.updates_btn.set_label(self.NO_UPDATES_FOUND_LABEL)
        else:
            self.updates_btn.set_icon_name('gl-arrow-circular-top-right')

        if updatable_apps:
            self.updates_btn.set_sensitive(True)

    def on_fetch_updates_btn_clicked(self, *args):
        self.update_all_btn.set_visible(False)
        self.fetch_updates()

    def trigger_filter_list(self, widget):
        if not self.installed_apps_list:
            return

        self.filter_query = widget.get_text()
        # self.installed_apps_list.invalidate_filter()

        for row in self.installed_apps_list_rows:
            if not getattr(row, 'force_show', False) and row._app.installed_status != InstalledStatus.INSTALLED:
                row.set_visible(False)
                continue

            if not len(self.filter_query):
                row.set_visible(True)
                continue

            visible = self.filter_query.lower().replace(' ', '') in row._app.name.lower()
            row.set_visible(visible)
            continue

        self.no_apps_found_row.set_visible(True)
        for row in self.installed_apps_list_rows:
            if row.get_visible():
                self.no_apps_found_row.set_visible(False)
                break

    def sort_installed_apps_list(self, row: AppListBoxItem, row1: AppListBoxItem):
        if (not hasattr(row1, '_app')):
            return 1

        if (not hasattr(row, '_app')) or (row._app.name.lower() < row1._app.name.lower()):
            return -1

        return 1

    def open_preferences(self, widget):
        pref = Preferences()
        pref.present()

    def on_update_all_btn_clicked(self, *args):
        self.emit('update-all', None)

    def on_open_welcome_screen(self, widget):
        tutorial = WelcomeScreen()
        tutorial.present(self)
