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

from .InstalledAppsList import InstalledAppsList
from .AppDetails import AppDetails
from .models.AppListElement import AppListElement
from .State import state
from .lib import utils

from gi.repository import Gtk, Adw, Gio


class BoutiqueWindow(Gtk.ApplicationWindow):
    def __init__(self, from_file=False, **kwargs):
        super().__init__(**kwargs)
        self.from_file = from_file

        # Create a container stack 
        self.container_stack = Gtk.Stack()

        # Create the "main_stack" widget we will be using in the Window
        self.app_lists_stack = Adw.ViewStack()

        self.titlebar = Adw.HeaderBar()
        self.view_title_widget = Adw.ViewSwitcherTitle(stack=self.app_lists_stack)
        self.left_button = Gtk.Button(icon_name='go-previous', visible=False)

        menu_obj = Gtk.Builder.new_from_resource('/it/mijorus/boutique/gtk/main-menu.xml')
        self.menu_button = Gtk.MenuButton(icon_name='open-menu', menu_model=menu_obj.get_object('primary_menu'))

        self.titlebar.pack_start(self.left_button)
        self.titlebar.pack_end(self.menu_button)
        
        self.titlebar.set_title_widget(self.view_title_widget)
        self.set_titlebar(self.titlebar)

        self.set_title('Boutique')
        self.set_default_size(700, 700)

        # Create the "stack" widget for the "installed apps" view
        self.installed_stack = Gtk.Stack()
        self.app_details = AppDetails()

        self.installed_apps_list = InstalledAppsList()
        self.installed_stack.add_child(self.installed_apps_list)

        self.installed_stack.set_visible_child(self.installed_apps_list)
        
        # Add content to the main_stack
        utils.add_page_to_adw_stack(self.app_lists_stack, self.installed_stack, 'installed', 'Installed', 'computer-symbolic' )

        self.container_stack.add_child(self.app_lists_stack)
        self.container_stack.add_child(self.app_details)
        self.set_child(self.container_stack)
        
        # Show details of an installed app
        self.installed_apps_list.connect('selected-app', self.on_selected_installed_app)
        self.app_details.connect('refresh-updatable', lambda _: self.installed_apps_list.refresh_upgradable())
        
        # left arrow click
        self.left_button.connect('clicked', self.on_left_button_clicked)
        # change visible child of the app list stack
        self.app_lists_stack.connect('notify::visible-child', self.on_app_lists_stack_change)
        # change visible child of the container stack
        self.container_stack.connect('notify::visible-child', self.on_container_stack_change)

    def on_selected_installed_app(self, source: Gtk.Widget, list_element: AppListElement):
        """Show app details"""

        self.app_details.set_app_list_element(list_element)
        self.container_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self.container_stack.set_visible_child(self.app_details)

    def on_selected_browsed_app(self, source: Gtk.Widget, custom_event: tuple[AppListElement, list[AppListElement]]):
        """Show details for an app from global search"""
        list_element, alt_sources = custom_event

        self.app_details.set_app_list_element(list_element, load_icon_from_network=True, alt_sources=alt_sources)
        # self.app_details.set_alt_sources(alt_sources)
        self.container_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self.container_stack.set_visible_child(self.app_details)

    def on_selected_local_file(self, file: Gio.File):
        if self.app_details.set_from_local_file(file):
            self.container_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
            self.container_stack.set_visible_child(self.app_details)

            if self.from_file:
                self.set_default_size(500, 550)
                self.left_button.set_visible(False)

        else:
            utils.send_notification(
                Gio.Notification.new('Unsupported file type: Boutique can\'t handle these types of files.')
            )

    def on_show_installed_list(self, source: Gtk.Widget=None, _=None):
        self.container_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
        self.left_button.set_visible(False)

        self.installed_apps_list.refresh_list()
        self.installed_apps_list.refresh_upgradable()
        self.container_stack.set_visible_child(self.app_lists_stack)

    def on_left_button_clicked(self, widget):
        if self.app_lists_stack.get_visible_child() == self.installed_stack:
            if self.container_stack.get_visible_child() == self.app_details:
                self.titlebar.set_title_widget(self.view_title_widget)
                self.on_show_installed_list()

        elif self.app_lists_stack.get_visible_child() == self.browse_stack:
            if self.container_stack.get_visible_child() == self.app_details:
                self.titlebar.set_title_widget(self.view_title_widget)
                self.on_show_browsed_list()

    def on_app_lists_stack_change(self, widget, _):
        if self.app_lists_stack.get_visible_child() == self.updates_stack:
            self.updates_list.on_show()

    def on_container_stack_change(self, widget, _):
        in_app_details = self.container_stack.get_visible_child() == self.app_details
        self.left_button.set_visible(in_app_details)
        self.view_title_widget.set_visible(not in_app_details)
