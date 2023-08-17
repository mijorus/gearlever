# window.py
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

import logging

from .lib.costants import APP_ID
from .InstalledAppsList import InstalledAppsList
from .AppDetails import AppDetails
from .providers.providers_list import appimage_provider
from .models.AppListElement import AppListElement
from .State import state
from .lib import utils

from gi.repository import Gtk, Adw, Gio, Gdk, GObject


class GearleverWindow(Gtk.ApplicationWindow):
    def __init__(self, from_file=False, **kwargs):
        super().__init__(**kwargs)
        self.from_file = from_file
        self.open_appimage_tooltip = _('Open a new AppImage')

        # Create a container stack 
        self.container_stack = Adw.Leaflet(can_unfold=False, can_navigate_back=True, can_navigate_forward=False)

        # Create the "main_stack" widget we will be using in the Window
        self.app_lists_stack = Adw.ViewStack()

        self.titlebar = Adw.HeaderBar()
        self.view_title_widget = Adw.ViewSwitcherTitle(stack=self.app_lists_stack)
        self.left_button = Gtk.Button(icon_name='plus-symbolic', tooltip_text=self.open_appimage_tooltip)

        menu_obj = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/main-menu.xml')
        self.menu_button = Gtk.MenuButton(icon_name='open-menu', menu_model=menu_obj.get_object('primary_menu'))

        self.titlebar.pack_start(self.left_button)
        self.titlebar.pack_end(self.menu_button)
        
        self.titlebar.set_title_widget(self.view_title_widget)
        self.set_titlebar(self.titlebar)

        self.set_title('Gear lever')
        self.set_default_size(700, 700)

        # Create the "stack" widget for the "installed apps" view
        self.installed_stack = Gtk.Stack()
        self.app_details = AppDetails()
        self.app_details.connect('uninstalled-app', self.on_uninstalled_app)

        self.installed_apps_list = InstalledAppsList()
        self.installed_apps_list.refresh_list()

        self.installed_stack.add_child(self.installed_apps_list)

        self.installed_stack.set_visible_child(self.installed_apps_list)
        
        # Add content to the main_stack
        utils.add_page_to_adw_stack(self.app_lists_stack, self.installed_stack, 'installed', 'Installed', 'computer-symbolic' )

        self.container_stack.append(self.app_lists_stack)
        self.container_stack.append(self.app_details)
        
        # Show details of an installed app
        self.installed_apps_list.connect('selected-app', self.on_selected_installed_app)

        # left arrow click
        self.left_button.connect('clicked', self.on_left_button_clicked)
        # change visible child of the app list stack
        self.app_lists_stack.connect('notify::visible-child', self.on_app_lists_stack_change)
        # change visible child of the container stack
        self.container_stack.connect('notify::visible-child', self.on_container_stack_change)

        builder = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/drag-drop.ui')
        self.drag_drop_ui = builder.get_object('drag-drop')

        self.drop_target_controller = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        self.drop_target_controller.connect('drop', self.on_drop_event)
        self.drop_target_controller.connect('enter', self.on_drop_enter)
        self.drop_target_controller.connect('leave', self.on_drop_leave)
        self.visible_before_dragdrop_start = None

        self.container_stack.add_controller(self.drop_target_controller)
        self.container_stack.append(self.drag_drop_ui)

        self.connect('close-request', self.on_close_request)

        self.set_child(self.container_stack)


    # Show app details
    def on_selected_installed_app(self, source: Gtk.Widget, list_element: AppListElement):
        self.app_details.set_app_list_element(list_element)
        self.container_stack.set_transition_type(Adw.LeafletTransitionType.OVER)
        self.container_stack.set_visible_child(self.app_details)

    def on_selected_local_file(self, file: Gio.File) -> bool:
        if self.app_details.set_from_local_file(file):
            self.container_stack.set_transition_type(
                Adw.LeafletTransitionType.UNDER if self.from_file else Adw.LeafletTransitionType.OVER
            )

            self.container_stack.set_visible_child(self.app_details)

            if self.from_file:
                # open the app with a minimal UI when opening a single file
                self.set_default_size(500, 550)
                self.left_button.set_visible(False)
                self.menu_button.set_visible(False)
                self.set_resizable(False)

            return True

        
        utils.send_notification(
            Gio.Notification.new('Unsupported file type: Gear lever can\'t handle these types of files.')
        )

        return False

    def on_show_installed_list(self, source: Gtk.Widget=None, data=None):
        self.container_stack.set_transition_type(Adw.LeafletTransitionType.OVER)

        self.installed_apps_list.refresh_list()
        self.container_stack.set_visible_child(self.app_lists_stack)

    def on_left_button_clicked(self, widget):
        if self.app_lists_stack.get_visible_child() == self.installed_stack:
            container_visible = self.container_stack.get_visible_child()

            if container_visible == self.app_details:
                self.titlebar.set_title_widget(self.view_title_widget)
                self.on_show_installed_list()

            elif container_visible == self.app_lists_stack:
                self.on_open_file_chooser()

    def on_app_lists_stack_change(self, widget, data):
        pass

    def on_container_stack_change(self, widget, data):
        in_app_details = self.container_stack.get_visible_child() is self.app_details
        self.left_button.set_icon_name('go-previous' if in_app_details else 'plus-symbolic')
        self.left_button.set_tooltip_text(None if in_app_details else self.open_appimage_tooltip)
        self.view_title_widget.set_visible(not in_app_details)

    def on_drop_event(self, widget, value, x, y):
        if isinstance(value, Gio.File):
            logging.debug('Opening file from drag and drop')
            return self.on_selected_local_file(value)

        return False
    
    def on_drop_enter(self, widget, x, y):
        self.container_stack.set_transition_type(Adw.LeafletTransitionType.UNDER)
        self.visible_before_dragdrop_start = self.container_stack.get_visible_child()
        self.container_stack.set_visible_child(self.drag_drop_ui)

        return Gdk.DragAction.COPY
    
    def on_drop_leave(self, widget):
        self.container_stack.set_transition_type(Adw.LeafletTransitionType.UNDER)

        if self.visible_before_dragdrop_start:
            self.container_stack.set_visible_child(self.visible_before_dragdrop_start)
        else:
            self.container_stack.set_visible_child(self.app_lists_stack)

        return Gdk.DragAction.COPY
    
    def on_uninstalled_app(self, widget, data):
        if self.from_file:
            return self.close()

        self.on_show_installed_list(widget, data)

    def on_open_file_chooser_response(self, dialog, result):
        try:
            selected_file = dialog.open_finish(result)
        except Exception as e:
            logging.error(str(e))
            return

        if selected_file:
            self.on_selected_local_file(selected_file)

    def on_open_file_chooser(self):
        dialog = Gtk.FileDialog(title=_('Open a file'),modal=True)

        dialog.open(
            parent=self,
            cancellable=None,
            callback=self.on_open_file_chooser_response
        )

    def on_close_request(self, widget):
        appimage_provider.extraction_folder_cleanup()