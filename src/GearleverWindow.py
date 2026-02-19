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

from .lib.constants import APP_ID
from .InstalledAppsList import InstalledAppsList
from .AppDetails import AppDetails
from .MultiInstall import MultiInstall
from .MultiUpdate import MultiUpdate
from .providers.providers_list import appimage_provider
from .providers.AppImageProvider import AppImageListElement
from .models.AppListElement import AppListElement
from .models.Settings import Settings
from .lib import utils

from gi.repository import Gtk, Adw, Gio, Gdk, GLib


class GearleverWindow(Adw.Window):
    def __init__(self, from_file=False, **kwargs):
        super().__init__(**kwargs)
        self.from_file = from_file
        self.selected_files_count = 0
        self.open_appimage_tooltip = _('Open a new AppImage')
        self.settings = Settings.settings

        # Create a container stack 
        self.container_stack = Adw.Leaflet(can_unfold=False, can_navigate_back=True, can_navigate_forward=False)

        # Create the "main_stack" widget we will be using in the Window
        self.app_lists_stack = Adw.ViewStack()

        self.titlebar = Adw.HeaderBar()
        self.view_title_widget = Adw.ViewSwitcherTitle(stack=self.app_lists_stack)
        self.open_appimage_button_child = Adw.ButtonContent(icon_name='gl-plus-symbolic', 
                                                            tooltip_text=self.open_appimage_tooltip, label=_('Open'))

        self.search_btn = Gtk.Button(child=Adw.ButtonContent(icon_name='gl-loupe-large'))
        self.search_btn.connect('clicked', self.on_trigger_search_mode)

        self.left_button = Gtk.Button(
            child=self.open_appimage_button_child
        )

        menu_obj = Gtk.Builder.new_from_resource('/it/mijorus/gearlever/gtk/main-menu.ui')
        self.menu_button = Gtk.MenuButton(icon_name='open-menu', menu_model=menu_obj.get_object('primary_menu'))

        self.titlebar.pack_start(self.left_button)
        self.titlebar.pack_end(self.menu_button)
        self.titlebar.pack_end(self.search_btn)
        
        self.titlebar.set_title_widget(self.view_title_widget)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self.titlebar)

        self.set_title('Gear lever')
        self.set_default_size(700, 700)

        toast_overlay = Adw.ToastOverlay()

        # Create the "stack" widget for the "installed apps" view
        self.installed_stack = Gtk.Stack()
        self.app_details = AppDetails()
        self.app_details.connect('uninstalled-app', self.on_uninstalled_app)
        self.app_details.connect('update-started', self.on_app_update_started)
        self.app_details.connect('update-ended', self.on_app_update_ended)

        self.installed_apps_list = InstalledAppsList()
        self.installed_apps_list.refresh_list()
        self.installed_apps_list.connect('update-all', self.on_update_all_event)

        self.multi_install = MultiInstall()
        self.multi_install.connect('show-details', self.on_multi_install_show_details)
        self.multi_install.connect('go-back', self.on_left_button_clicked)

        self.multi_update = MultiUpdate()
        self.multi_update.connect('go-back', self.on_left_button_clicked)

        self.installed_stack.add_child(self.installed_apps_list)
        self.installed_stack.set_visible_child(self.installed_apps_list)
        
        # Add content to the main_stack
        utils.add_page_to_adw_stack(self.app_lists_stack, self.installed_stack, 
                                    'installed', 'Installed', 'gearlever-computer-symbolic' )

        self.container_stack.append(self.app_lists_stack)
        self.container_stack.append(self.app_details)
        self.container_stack.append(self.multi_install)
        self.container_stack.append(self.multi_update)

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
        self.drop_target_controller.set_gtypes([Gdk.FileList])

        self.drop_target_controller.connect('drop', self.on_drop_event)
        self.drop_target_controller.connect('enter', self.on_drop_enter)
        self.drop_target_controller.connect('leave', self.on_drop_leave)
        self.visible_before_dragdrop_start = None

        self.container_stack.add_controller(self.drop_target_controller)
        self.container_stack.append(self.drag_drop_ui)

        self.connect('close-request', self.on_close_request)
        self.connect('notify::maximized', self.on_window_maximixed_changed)

        toast_overlay.set_child(self.container_stack)

        toolbar_view.set_content(toast_overlay)
        self.set_content(toolbar_view)

        if self.settings.get_boolean('is-maximized'):
            self.maximize()

    # Show app details
    def on_selected_installed_app(self, source: Gtk.Widget, list_element: AppListElement):
        self.selected_files_count = 0
        self.app_details.set_app_list_element(list_element)
        self.container_stack.set_transition_type(Adw.LeafletTransitionType.OVER)
        self.container_stack.set_visible_child(self.app_details)

    def on_selected_local_file(self, files: list[Gio.File]) -> bool:
        if files:
            self.container_stack.set_transition_type(
                Adw.LeafletTransitionType.UNDER if self.from_file else Adw.LeafletTransitionType.OVER
            )

        if len(files) == 1 and self.app_details.set_from_local_file(files[0]):
            self.container_stack.set_visible_child(self.app_details)

            if self.from_file:
                if self.settings.get_boolean('preview-minimal-ui'):
                    self.app_details.set_minimal_ui(True)
                    self.set_default_size(-1, -1)
                    self.set_resizable(False)

                # open the app with a minimal UI when opening a single file
                self.left_button.set_visible(False)
                self.menu_button.set_visible(False)

            return True

        elif len(files) > 1 and self.multi_install.set_from_local_files(files):
            self.container_stack.set_visible_child(self.multi_install)

            if self.from_file:
                # open the app with a minimal UI when opening a single file
                self.left_button.set_visible(False)
                self.menu_button.set_visible(False)

            return True

        utils.send_notification(
            Gio.Notification.new('Unsupported file type: Gear lever can\'t handle these types of files.')
        )

        return False

    def on_multi_install_show_details(self, source: MultiInstall, el: AppImageListElement):
        file = Gio.File.new_for_path(el.file_path)
        self.on_selected_local_file([file])

    def on_show_installed_list(self, source: Gtk.Widget=None, data=None):
        self.container_stack.set_transition_type(Adw.LeafletTransitionType.OVER)

        # self.installed_apps_list.refresh_list()
        self.container_stack.set_visible_child(self.app_lists_stack)

    def on_left_button_clicked(self, *args):
        if self.app_lists_stack.get_visible_child() == self.installed_stack:
            container_visible = self.container_stack.get_visible_child()

            if container_visible == self.app_details:
                if self.selected_files_count > 1:
                    self.container_stack.set_visible_child(self.multi_install)

                else:
                    self.titlebar.set_title_widget(self.view_title_widget)
                    self.on_show_installed_list()

            elif container_visible == self.multi_install:
                self.titlebar.set_title_widget(self.view_title_widget)
                self.on_show_installed_list()

            elif container_visible == self.multi_update:
                self.titlebar.set_title_widget(self.view_title_widget)
                self.on_show_installed_list()

            elif container_visible == self.app_lists_stack:
                self.on_open_file_chooser()

    def on_app_lists_stack_change(self, widget, data):
        pass

    def on_update_all_event(self, *args):
        self.container_stack.set_visible_child(self.multi_update)
        self.multi_update.start()

    def on_container_stack_change(self, widget, data):
        in_app_details = self.container_stack.get_visible_child() is self.app_details
        in_multi_install = self.container_stack.get_visible_child() is self.multi_install
        in_multi_update = self.container_stack.get_visible_child() is self.multi_update
        in_apps_list = self.container_stack.get_visible_child() is self.app_lists_stack

        if in_app_details or in_multi_install:
            self.left_button.set_icon_name('gl-left-symbolic')
            self.left_button.set_tooltip_text(None)
            self.search_btn.set_visible(False)
        elif in_multi_update:
            self.left_button.set_visible(False)
        else:
            self.search_btn.set_visible(True)
            self.left_button.set_child(self.open_appimage_button_child)

        if in_apps_list:
            self.installed_apps_list.refresh_list()

        self.view_title_widget.set_visible(not in_app_details)

    def on_drop_event(self, widget, value, x, y):
        if isinstance(value, Gdk.FileList):
            logging.debug('Opening file from drag and drop')
            self.selected_files_count = len(list(value))
            return self.on_selected_local_file(list(value))

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

    def on_app_update_started(self, *args):
        self.left_button.set_visible(False)
        self.left_button.set_sensitive(False)

    def on_app_update_ended(self, *args):
        self.left_button.set_visible(True)
        self.left_button.set_sensitive(True)


    def on_open_file_chooser_response(self, dialog, result):
        try:
            selected_files = dialog.open_multiple_finish(result)
            self.selected_files_count = len(list(selected_files))
        except Exception as e:
            logging.error(str(e))
            return

        if selected_files:
            self.on_selected_local_file(list(selected_files))

    def on_open_file_chooser(self):
        dialog = Gtk.FileDialog(title=_('Open a file'), modal=True)

        dialog.open_multiple(
            parent=self,
            cancellable=None,
            callback=self.on_open_file_chooser_response
        )

    def on_close_request(self, widget):
        appimage_provider.extraction_folder_cleanup()

    def on_window_maximixed_changed(self, *args):
        self.settings.set_boolean('is-maximized', self.is_maximized())

    def on_trigger_search_mode(self, *args):
        self.installed_apps_list.trigger_search_mode()
