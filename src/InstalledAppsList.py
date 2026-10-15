from gi.repository import Gtk, Adw, GObject, Gio, GLib
from typing import Dict, List, Optional

import logging

from time import sleep
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageListElement
from .models.AppListElement import InstalledStatus
from .components.FilterEntry import FilterEntry
from .components.CustomComponents import NoAppsFoundRow
from .components.AppListBoxItem import AppListBoxItem
from .components.AppGridBoxItem import AppGridBoxItem
from .preferences import Preferences
from .WelcomeScreen import WelcomeScreen
from .lib.utils import get_application_window, check_internet, show_message_dialog, show_remove_confirm_dialog
from .lib.async_utils import _async, idle
from .models.UpdateManagerChecker import UpdateManagerChecker
from .models.Settings import Settings

fetch_updates_cache = None

class InstalledAppsList(Gtk.ScrolledWindow):
    __gsignals__ = {
        "selected-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
        "update-all": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    CHECK_FOR_UPDATES_LABEL = _('Check for updates')
    NO_UPDATES_FOUND_LABEL = _('No updates found')
    CHECKING_FOR_UPDATES_LABEL = _('Checking updates...')
    NO_CONNECTION_LABEL = _('No Connection')
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

        self.installed_apps_grid = Gtk.FlowBox(
            valign=Gtk.Align.START,
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            column_spacing=6,
            row_spacing=6,
            min_children_per_line=2,
            max_children_per_line=30,
        )
        self.installed_apps_grid.connect('child-activated', self.on_activated_grid_child)

        self.view_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.view_stack.add_named(self.installed_apps_list_slot, 'list')
        self.view_stack.add_named(self.installed_apps_grid, 'grid')

        self.installed_apps_list_rows: List[AppListBoxItem] = []
        self.installed_apps_grid_rows: List[AppGridBoxItem] = []
        # file paths of apps being updated from a grid card; survives refresh_list()
        self.grid_updates_in_progress: set[str] = set()
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

        # list/grid view switcher
        saved_view_mode = Settings.settings.get_string('installed-apps-view-mode')

        self.view_list_btn = Gtk.ToggleButton(
            icon_name='view-list-symbolic',
            tooltip_text=_('List view'),
            active=(saved_view_mode != 'grid'),
        )
        self.view_grid_btn = Gtk.ToggleButton(
            icon_name='view-grid-symbolic',
            tooltip_text=_('Grid view'),
            group=self.view_list_btn,
            active=(saved_view_mode == 'grid'),
        )

        self.view_list_btn.connect('toggled', self.on_view_mode_toggled)
        self.view_grid_btn.connect('toggled', self.on_view_mode_toggled)

        view_mode_switcher = Gtk.Box(css_classes=['linked'])
        view_mode_switcher.append(self.view_list_btn)
        view_mode_switcher.append(self.view_grid_btn)

        self.view_stack.set_visible_child_name('grid' if saved_view_mode == 'grid' else 'list')

        self.updates_btn.connect('clicked', self.on_fetch_updates_btn_clicked)
        self.update_all_btn.connect('clicked', self.on_update_all_btn_clicked)
        title_row.append(view_mode_switcher)
        title_row.append(self.updates_btn)
        title_row.append(self.update_all_btn)

        [self.main_box.append(el) for el in [title_row, self.view_stack, self.no_apps_found_row]]

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
        Settings.settings.connect('changed::appimages-default-folder', lambda *_: self.refresh_list())

    # Emit and event that changes the active page of the Stack in the parent widget
    def on_activated_row(self, listbox, row: Gtk.ListBoxRow):
        self.filter_entry.set_search_mode(False)
        self.emit('selected-app', row._app)

    def on_activated_grid_child(self, flowbox, child: Gtk.FlowBoxChild):
        self.filter_entry.set_search_mode(False)
        self.emit('selected-app', child._app)

    def on_view_mode_toggled(self, btn: Gtk.ToggleButton):
        if not btn.get_active():
            return

        mode = 'grid' if btn is self.view_grid_btn else 'list'
        self.view_stack.set_visible_child_name(mode)
        Settings.settings.set_string('installed-apps-view-mode', mode)

    def trigger_search_mode(self):
        self.filter_entry.set_search_mode(
            not self.filter_entry.get_search_mode()
        )

    def refresh_list(self):
        self.installed_apps_list.remove_all()
        self.installed_apps_grid.remove_all()
        self.updates_btn.set_label(self.CHECK_FOR_UPDATES_LABEL)
        self.installed_apps_list_rows = []
        self.installed_apps_grid_rows = []

        installed: List[AppImageListElement] = appimage_provider.list_installed()

        for i in installed:
            list_row = AppListBoxItem(i, activatable=True, selectable=False, hexpand=True)
            list_row.set_update_version(i.version, i.size)
            # get_icon() can extract the AppImage when no icon is cached, so load it once for both views
            icon = appimage_provider.get_icon(i)
            list_row.set_icon(icon)
            self.installed_apps_list_rows.append(list_row)
            self.installed_apps_list.append(list_row)

            grid_row = AppGridBoxItem(i)
            grid_row.set_update_version(i.version)
            grid_row.set_icon(self.clone_image(icon))
            grid_row.connect('launch-app', self.on_grid_item_launch)
            grid_row.connect('update-app', self.on_grid_item_update)
            grid_row.connect('remove-app', self.on_grid_item_remove)
            if i.file_path in self.grid_updates_in_progress:
                grid_row.set_busy(True)

            self.installed_apps_grid_rows.append(grid_row)
            self.installed_apps_grid.append(grid_row)

        if installed:
            self.container_stack.set_visible_child(self.clamp_container)
        else:
            self.container_stack.set_visible_child(self.placeholder)

        self.no_apps_found_row.set_visible(False)

        self.installed_apps_list.set_sort_func(lambda r1, r2: self.sort_installed_apps_list(r1, r2))
        self.installed_apps_list.invalidate_sort()

        self.installed_apps_grid.set_sort_func(lambda r1, r2: self.sort_installed_apps_list(r1, r2))
        self.installed_apps_grid.invalidate_sort()

        self.update_all_btn.set_visible(False)

    @_async
    def fetch_updates(self, cache=False):
        global fetch_updates_cache

        if not check_internet():
            def _show_no_connection():
                self.updates_btn.set_label(self.NO_CONNECTION_LABEL)
                self.updates_btn.add_css_class('destructive-action')
                self.updates_btn.set_sensitive(True)

            def _reset_btn():
                self.updates_btn.set_label(self.CHECK_FOR_UPDATES_LABEL)
                self.updates_btn.remove_css_class('destructive-action')
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_show_no_connection)
            GLib.timeout_add_seconds(3, _reset_btn)
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

            logging.debug(f'Found app with update url: {manager.name}')

            try:
                status = manager.is_update_available()

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
        for row in [*self.installed_apps_list_rows, *self.installed_apps_grid_rows]:
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

        for row in [*self.installed_apps_list_rows, *self.installed_apps_grid_rows]:
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

    def clone_image(self, image: Gtk.Image) -> Gtk.Image:
        # a widget can only have one parent, so the grid needs its own Gtk.Image
        storage = image.get_storage_type()

        if storage == Gtk.ImageType.PAINTABLE:
            return Gtk.Image.new_from_paintable(image.get_paintable())
        if storage == Gtk.ImageType.GICON:
            return Gtk.Image.new_from_gicon(image.get_gicon())
        if storage == Gtk.ImageType.ICON_NAME:
            return Gtk.Image.new_from_icon_name(image.get_icon_name())

        return Gtk.Image(icon_name='gl-application-x-executable-symbolic')

    def on_grid_item_launch(self, card: AppGridBoxItem, app: AppImageListElement):
        try:
            appimage_provider.run(app)
        except Exception as e:
            logging.error('Launch error', exc_info=e)
            show_message_dialog(str(e))
            return

        # avoid spawning the app several times on repeated clicks
        def _restore_launch_btn():
            card.launch_btn.set_sensitive(True)
            return GLib.SOURCE_REMOVE

        card.launch_btn.set_sensitive(False)
        GLib.timeout_add_seconds(3, _restore_launch_btn)

    def on_grid_item_update(self, card: AppGridBoxItem, app: AppImageListElement):
        if app.file_path in self.grid_updates_in_progress:
            return

        self.grid_updates_in_progress.add(app.file_path)
        card.set_busy(True)
        self.run_grid_item_update(app)

    @_async
    def run_grid_item_update(self, app: AppImageListElement):
        manager = None

        try:
            if appimage_provider.is_app_running(app):
                raise Exception(_('{app_name} is running, please close it before proceeding with the update').format(app_name=app.name))

            manager = UpdateManagerChecker.check_url_for_app(app)
            if manager:
                appimage_provider.update_from_url(manager, app,
                    status_cb=lambda perc: GLib.idle_add(self.set_grid_update_progress, app.file_path, perc))
        except Exception as e:
            logging.error('Update error', exc_info=e)
            GLib.idle_add(show_message_dialog, str(e))
        finally:
            if manager:
                manager.cleanup()

            def _complete():
                self.grid_updates_in_progress.discard(app.file_path)
                self.refresh_list()

            GLib.idle_add(_complete)

    def set_grid_update_progress(self, file_path: str, fraction: float):
        # look the card up each time: refresh_list() may have replaced it mid-update
        for row in self.installed_apps_grid_rows:
            if row._app.file_path == file_path:
                row.set_progress(fraction)

    def on_grid_item_remove(self, card, app: AppImageListElement):
        show_remove_confirm_dialog(self.on_grid_item_remove_confirm, app)

    def on_grid_item_remove_confirm(self, dialog, response: str, app: AppImageListElement):
        if response == 'remove':
            try:
                appimage_provider.uninstall(app)
            except Exception as e:
                logging.error('Uninstall error', exc_info=e)
                show_message_dialog(str(e))

            self.refresh_list()
