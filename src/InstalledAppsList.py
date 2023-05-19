import threading
import asyncio
from urllib import request
from gi.repository import Gtk, Adw, Gdk, GObject, Pango
from typing import Dict, List, Optional
import re

from .providers.providers_list import providers
from .models.AppListElement import AppListElement, InstalledStatus
from .models.Provider import Provider
from .models.Models import AppUpdateElement
from .components.FilterEntry import FilterEntry
from .components.CustomComponents import NoAppsFoundRow
from .components.AppListBoxItem import AppListBoxItem
from .lib.utils import set_window_cursor, key_in_dict, log

class InstalledAppsList(Gtk.ScrolledWindow):
    __gsignals__ = {
        "selected-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.installed_apps_list_slot = Gtk.Box()
        self.installed_apps_list: Optional[Gtk.ListBox] = None
        self.installed_apps_list_rows: List[Gtk.ListBoxRow] = []
        self.no_apps_found_row = NoAppsFoundRow(visible=False)

        # Create the filter search bar
        self.filter_query: str = ''
        self.filter_entry = FilterEntry('Filter installed applications', capture=self, margin_bottom=20)
        self.filter_entry.connect('search-changed', self.trigger_filter_list)

        self.refresh_list()

        # updates row
        self.updates_fetched = False
        self.updates_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, visible=True)

        ## the list box containing all the updatable apps
        self.updates_row_list = Gtk.ListBox(css_classes=["boxed-list"], margin_bottom=25)
        self.updates_row_list_spinner = Gtk.ListBoxRow(child=Gtk.Spinner(spinning=True, margin_top=5, margin_bottom=5), visible=False)
        self.updates_row_list.append(self.updates_row_list_spinner)
        self.updates_row_list.connect('row-activated', self.on_activated_row)
        ## an array containing all the updatable apps, used for some custom login
        self.updates_row_list_items: list = []
        self.updates_revealter = Gtk.Revealer(child=self.updates_row, transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, reveal_child=False)

        updates_title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, valign=Gtk.Align.CENTER, margin_bottom=5)

        self.updates_title_label = Gtk.Label(label='', css_classes=['title-4'], hexpand=True, halign=Gtk.Align.START)
        updates_title_row.append( self.updates_title_label )
        
        self.update_all_btn = Gtk.Button(label='Update all', css_classes=['suggested-action'], valign=Gtk.Align.CENTER) 
        self.update_all_btn.connect('clicked', self.on_update_all_btn_clicked)

        updates_title_row.append(self.update_all_btn)
        self.updates_row.append(updates_title_row)
        self.updates_row.append(self.updates_row_list)

        # title row
        title_row = Gtk.Box(margin_bottom=5)
        title_row.append( Gtk.Label(label='Installed applications', css_classes=['title-2']) )

        for el in [self.filter_entry, self.updates_revealter, title_row, self.installed_apps_list_slot]:
            self.main_box.append(el)

        clamp = Adw.Clamp(child=self.main_box, maximum_size=600, margin_top=20, margin_bottom=20)

        self.refresh_upgradable()
        self.set_child(clamp)

    def on_activated_row(self, listbox, row: Gtk.ListBoxRow):
        """Emit and event that changes the active page of the Stack in the parent widget"""
        if not self.update_all_btn.get_sensitive() or not self.updates_fetched:
            return

        self.emit('selected-app', row._app)

    def refresh_list(self):
        set_window_cursor('wait')
        if self.installed_apps_list:
            self.installed_apps_list_slot.remove(self.installed_apps_list)

        self.installed_apps_list= Gtk.ListBox(css_classes=["boxed-list"])
        self.installed_apps_list_rows = []

        for p, provider in providers.items():
            installed: List[AppListElement] = provider.list_installed()

            for i in installed:
                list_row = AppListBoxItem(i, activatable=True, selectable=True, hexpand=True)
                list_row.set_update_version(key_in_dict(i.extra_data, 'version'))

                list_row.load_icon(load_from_network=False)
                self.installed_apps_list_rows.append(list_row)
                self.installed_apps_list.append(list_row)

        self.installed_apps_list.append(self.no_apps_found_row)
        self.no_apps_found_row.set_visible(False)
        self.installed_apps_list_slot.append(self.installed_apps_list)
        
        self.installed_apps_list.set_sort_func(lambda r1, r2: self.sort_installed_apps_list(r1, r2))
        self.installed_apps_list.invalidate_sort()

        self.installed_apps_list.connect('row-activated', self.on_activated_row)
        set_window_cursor('default')

    def trigger_filter_list(self, widget):
        """ Implements a custom filter function"""
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

    def _refresh_upgradable_thread(self, only_provider: Optional[str]=None):
        """Runs the background task to check for app updates"""
        for widget in self.updates_row_list_items:
            self.updates_row_list.remove(widget)

        self.updates_row_list_items = []

        if self.installed_apps_list:
            self.installed_apps_list.set_opacity(0.5)

        self.updates_revealter.set_reveal_child(not self.updates_fetched)
        self.updates_title_label.set_label('Searching for updates...')

        upgradable = 0
        self.updates_row_list_spinner.set_visible(True)

        for p, provider in providers.items():
            updatable_elements = provider.list_updatables()

            updatable_libs: list[AppUpdateElement] = []
            for upg in updatable_elements:
                update_is_an_app = False

                for row in self.installed_apps_list_rows:
                    if row._app.id == upg.id:
                        update_is_an_app = True

                        upgradable += 1
                        app_list_item = AppListBoxItem(row._app, activatable=True, selectable=True, hexpand=True)
                        app_list_item.force_show = True
                        
                        if upg.to_version and ('version' in row._app.extra_data):
                            app_list_item.set_update_version(f'{row._app.extra_data["version"]} > {upg.to_version}')

                        app_list_item.load_icon()
                        self.updates_row_list.append( app_list_item )
                        self.updates_row_list_items.append( app_list_item )
                        row._app.set_installed_status(InstalledStatus.UPDATE_AVAILABLE)
                        break

                if not update_is_an_app:
                    updatable_libs.append(upg)

            if updatable_libs:
                upgradable += 1
                updatable_libs_desc = ', '.join([upl.id for upl in updatable_libs])

                lib_list_element = AppListElement(
                    'System libraries', 
                    'The following libraries can be updated: ' + updatable_libs_desc, 
                    '__updatable_libs__', 
                    'flatpak', 
                    InstalledStatus.UPDATE_AVAILABLE
                )

                app_list_item = AppListBoxItem(lib_list_element, activatable=False, selectable=False, hexpand=True)
                app_list_item.force_show = True
                
                if upg.to_version and ('version' in row._app.extra_data):
                    app_list_item.set_update_version(f'{row._app.extra_data["version"]} > {upg.to_version}')

                app_list_item.load_icon()
                self.updates_row_list.append( app_list_item )
                self.updates_row_list_items.append( app_list_item )
                row._app.set_installed_status(InstalledStatus.UPDATE_AVAILABLE)


        self.updates_fetched = True
        self.updates_row_list_spinner.set_visible(False)
        self.installed_apps_list.set_opacity(1)
        self.updates_revealter.set_reveal_child(upgradable > 0)
        self.updates_title_label.set_label('Available updates')
        self.trigger_filter_list(self.filter_entry)

    def refresh_upgradable(self, only_provider: Optional[str]=None):
        self.updates_fetched = True
        # for p, provider in providers.items():
        #     if provider.updates_need_refresh():
        #         thread = threading.Thread(target=self._refresh_upgradable_thread, args=(only_provider, ), daemon=True)
        #         thread.start()

        #         break

    def after_update_all(self, result: bool, prov: str):
        if result and (not self.update_all_btn.has_css_class('destructive-action')):
            if self.updates_row_list and prov == [*providers.keys()][-1]:
                self.updates_row_list.set_opacity(1)
                self.update_all_btn.set_sensitive(True)
                self.update_all_btn.set_label('Update all')

        else:
            self.update_all_btn.set_label('Error')
            self.update_all_btn.set_css_classes(['destructive-action'])

        self.refresh_upgradable(only_provider=prov)

    def on_update_all_btn_clicked(self, widget: Gtk.Button):
        if not self.updates_row_list:
            return

        self.updates_row_list.set_opacity(0.5)
        self.update_all_btn.set_sensitive(False)
        self.update_all_btn.set_label('Updating...')

        for p, provider in providers.items():
            provider.update_all(self.after_update_all)

    def sort_installed_apps_list(self, row: AppListBoxItem, row1: AppListBoxItem):
        if (not hasattr(row1, '_app')):
            return 1

        if (not hasattr(row, '_app')) or (row._app.name.lower() < row1._app.name.lower()):
            return -1

        return 1