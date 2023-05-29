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
from .lib.utils import set_window_cursor, key_in_dict, log

class InstalledAppsList(Gtk.ScrolledWindow):
    __gsignals__ = {
        "selected-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self):
        super().__init__()

        self.container_stack = Gtk.Stack()
        self.container_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

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
        
        self.updates_row.append(updates_title_row)
        self.updates_row.append(self.updates_row_list)

        # title row
        title_row = Gtk.Box(margin_bottom=5)
        title_row.append( Gtk.Label(label='Installed applications', css_classes=['title-2']) )

        for el in [self.filter_entry, self.updates_revealter, title_row, self.installed_apps_list_slot]:
            self.main_box.append(el)

        self.clamp = Adw.Clamp(child=self.main_box, maximum_size=600, margin_top=20, margin_bottom=20)

        # empty list placeholder
        builder = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/empty-list-placeholder.ui')
        self.placeholder = builder.get_object('target')

        self.container_stack.add_child(self.clamp)
        self.container_stack.add_child(self.placeholder)

        self.set_child(self.container_stack)
        state.connect__('appimages-default-folder', lambda k: self.refresh_list())

    # Emit and event that changes the active page of the Stack in the parent widget
    def on_activated_row(self, listbox, row: Gtk.ListBoxRow):
        self.emit('selected-app', row._app)

    def refresh_list(self):
        set_window_cursor('wait')
        if self.installed_apps_list:
            self.installed_apps_list_slot.remove(self.installed_apps_list)

        self.installed_apps_list= Gtk.ListBox(css_classes=["boxed-list"])
        self.installed_apps_list_rows = []

        installed: List[AppImageListElement] = appimage_provider.list_installed()

        for i in installed:
            list_row = AppListBoxItem(i, activatable=True, selectable=True, hexpand=True)
            list_row.set_update_version(i.version)

            list_row.load_icon()
            self.installed_apps_list_rows.append(list_row)
            self.installed_apps_list.append(list_row)

        if installed:
            self.container_stack.set_visible_child(self.clamp)
        else:
            self.container_stack.set_visible_child(self.placeholder)

        self.installed_apps_list.append(self.no_apps_found_row)
        self.no_apps_found_row.set_visible(False)
        self.installed_apps_list_slot.append(self.installed_apps_list)
        
        self.installed_apps_list.set_sort_func(lambda r1, r2: self.sort_installed_apps_list(r1, r2))
        self.installed_apps_list.invalidate_sort()

        self.installed_apps_list.connect('row-activated', self.on_activated_row)
        set_window_cursor('default')

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