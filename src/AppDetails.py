import threading
import time
import logging
from typing import Optional, Callable
from .lib.utils import qq
from gi.repository import Gtk, GObject, Adw, Gdk, Gio, Pango, GLib
from .State import state
from .models.AppListElement import InstalledStatus
from .providers.AppImageProvider import AppImageListElement
from .providers.providers_list import appimage_provider
from .lib.async_utils import _async, idle
from .lib.utils import cleanhtml, key_in_dict, set_window_cursor, get_application_window
from .components.CustomComponents import CenteringBox, LabelStart


class AppDetails(Gtk.ScrolledWindow):
    """The presentation screen for an application"""

    def __init__(self):
        super().__init__()
        self.app_list_element: AppImageListElement = None
        self.common_btn_css_classes = ['pill', 'text-button']

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=10, margin_bottom=10, margin_start=20, margin_end=20,)

        # 1st row
        self.details_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.icon_slot = Gtk.Box()

        title_col = CenteringBox(orientation=Gtk.Orientation.VERTICAL, hexpand=True, spacing=2)
        self.title = Gtk.Label(label='', css_classes=['title-1'], hexpand=True, halign=Gtk.Align.CENTER)
        self.version = Gtk.Label(label='', halign=Gtk.Align.CENTER, css_classes=['dim-label'])
        self.app_id = Gtk.Label(
            label='',
            halign=Gtk.Align.CENTER,
            css_classes=['dim-label'],
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=100,
        )

        for el in [self.title, self.app_id, self.version]:
            title_col.append(el)

        self.source_selector_hdlr = None
        self.source_selector = Gtk.ComboBoxText()
        self.source_selector_revealer = Gtk.Revealer(child=self.source_selector, transition_type=Gtk.RevealerTransitionType.CROSSFADE)

        # Trust app check button
        self.trust_app_check_button = Gtk.CheckButton(label=_('I have verified the source of this app'))
        self.trust_app_check_button.connect('toggled', self.after_trust_buttons_interaction)

        self.trust_app_check_button_revealer = Gtk.Revealer(
            child=self.trust_app_check_button, 
        )

        # Action buttons
        self.primary_action_button = Gtk.Button(label='', valign=Gtk.Align.CENTER, css_classes=self.common_btn_css_classes)
        self.secondary_action_button = Gtk.Button(label='', valign=Gtk.Align.CENTER, visible=False, css_classes=self.common_btn_css_classes)

        action_buttons_row = CenteringBox(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.primary_action_button.connect('clicked', self.on_primary_action_button_clicked)
        self.secondary_action_button.connect('clicked', self.on_secondary_action_button_clicked)

        for el in [self.trust_app_check_button_revealer, self.secondary_action_button, self.primary_action_button]:
            action_buttons_row.append(el)

        for el in [self.icon_slot, title_col, action_buttons_row]:
            self.details_row.append(el)

        # preview row
        self.previews_row = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=20,
        )

        # row
        self.desc_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=20, margin_bottom=20)
        self.description = Gtk.Label(label='', halign=Gtk.Align.START, wrap=True, selectable=True)

        self.desc_row_spinner = Gtk.Spinner(spinning=True, visible=True)
        self.desc_row.append(self.desc_row_spinner)

        self.desc_row.append(self.description)

        # row
        self.third_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.extra_data = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.third_row.append(self.extra_data)

        for el in [self.details_row, self.previews_row, self.desc_row, self.third_row]:
            self.main_box.append(el)

        clamp = Adw.Clamp(child=self.main_box, maximum_size=600, margin_top=10, margin_bottom=20)
        
        self.set_trust_button(trusted=True)
        self.set_child(clamp)

    def set_app_list_element(self, el: AppImageListElement, local_file=False):
        self.app_list_element = el
        self.local_file = local_file
        self.provider = appimage_provider

        self.load()

    def set_from_local_file(self, file: Gio.File):
        if appimage_provider.can_install_file(file):
            list_element = appimage_provider.create_list_element_from_file(file)

            self.set_trust_button(trusted=(list_element.installed_status is InstalledStatus.INSTALLED))

            self.set_app_list_element(list_element)
            return True

        logging.warn('Trying to open an unsupported file')
        return False


    @idle
    def complete_load(self, icon: Gtk.Image, load_completed_callback: Optional[Callable]):
        self.show_row_spinner(True)

        self.details_row.remove(self.icon_slot)
        self.icon_slot = icon
        icon.set_pixel_size(128)
        self.details_row.prepend(self.icon_slot)

        self.title.set_label(cleanhtml(self.app_list_element.name))

        version_label = key_in_dict(self.app_list_element.extra_data, 'version')
        self.version.set_markup('' if not version_label else f'<small>{version_label}</small>')
        self.app_id.set_markup(f'<small>{self.app_list_element.id}</small>')
        self.description.set_label(
            self.provider.get_description(self.app_list_element)
        )

        self.third_row.remove(self.extra_data)
        self.extra_data = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.third_row.append(self.extra_data)

        self.install_button_label_info = None

        self.load_extra_details()

        self.update_installation_status()
        self.show_row_spinner(False)

        if load_completed_callback is not None:
            load_completed_callback()

    @_async
    def load(self, load_completed_callback: Optional[Callable]=None):
        self.show_row_spinner(True)
        icon = Gtk.Image(icon_name='application-x-executable-symbolic')

        if self.trust_app_check_button.get_active():
            icon = self.provider.get_icon(self.app_list_element)
            self.provider.refresh_title(self.app_list_element)

        self.complete_load(icon, load_completed_callback)

    @_async
    def install_file(self, el: AppImageListElement):
        try:
            self.provider.install_file(el)
        except Exception as e:
            logging.error(str(e))

        self.update_installation_status()

    def on_primary_action_button_clicked(self, button: Gtk.Button):
        if self.app_list_element.installed_status == InstalledStatus.INSTALLED:
            self.app_list_element.set_installed_status(InstalledStatus.UNINSTALLING)
            self.update_installation_status()

            self.provider.uninstall(self.app_list_element)

        elif self.app_list_element.installed_status == InstalledStatus.UNINSTALLING:
            pass

        elif self.app_list_element.installed_status == InstalledStatus.NOT_INSTALLED:
            self.app_list_element.set_installed_status(InstalledStatus.INSTALLING)

            if self.trust_app_check_button.get_active():
                self.update_installation_status()
                self.install_file(self.app_list_element)

        elif self.app_list_element.installed_status == InstalledStatus.UPDATE_AVAILABLE:
            self.provider.uninstall(self.app_list_element)

        self.update_installation_status()

    def on_secondary_action_button_clicked(self, button: Gtk.Button):
        if self.app_list_element.installed_status in [InstalledStatus.INSTALLED, InstalledStatus.NOT_INSTALLED]:
            if self.trust_app_check_button.get_active():
                try:
                    self.provider.run(self.app_list_element)
                except Exception as e:
                    logging.error(str(e))

        elif self.app_list_element.installed_status == InstalledStatus.UPDATE_AVAILABLE:
            self.app_list_element.set_installed_status(InstalledStatus.UPDATING)
            self.update_installation_status()
            self.provider.update(self.app_list_element)

    def update_status_callback(self, status: bool):
        if not status:
            self.app_list_element.set_installed_status(InstalledStatus.ERROR)

        self.update_installation_status()

    def update_installation_status(self):
        self.primary_action_button.set_css_classes(self.common_btn_css_classes)
        self.secondary_action_button.set_visible(False)
        self.secondary_action_button.set_css_classes(self.common_btn_css_classes)
        self.source_selector.set_visible(False)

        if self.app_list_element.installed_status == InstalledStatus.INSTALLED:
            self.secondary_action_button.set_label(_('Launch'))
            self.secondary_action_button.set_visible(True)

            self.primary_action_button.set_label(_('Remove'))
            self.primary_action_button.set_css_classes([*self.common_btn_css_classes, 'destructive-action'])

        elif self.app_list_element.installed_status == InstalledStatus.UNINSTALLING:
            self.primary_action_button.set_label(_('Uninstalling...'))

        elif self.app_list_element.installed_status == InstalledStatus.INSTALLING:
            self.primary_action_button.set_label(_('Installing...'))

        elif self.app_list_element.installed_status == InstalledStatus.NOT_INSTALLED:
            # self.secondary_action_button.set_sensitive(False)
            # self.primary_action_button.set_sensitive(False)

            self.secondary_action_button.set_visible(True)
            self.primary_action_button.set_css_classes([*self.common_btn_css_classes, 'suggested-action'])

            self.primary_action_button.set_label(_('Move to the app menu'))
            self.secondary_action_button.set_label(_('Launch'))

        elif self.app_list_element.installed_status == InstalledStatus.UPDATE_AVAILABLE:
            self.secondary_action_button.set_label(_('Update'))
            self.secondary_action_button.set_css_classes([*self.common_btn_css_classes, 'suggested-action'])
            self.secondary_action_button.set_visible(True)

            self.primary_action_button.set_label(_('Remove'))
            self.primary_action_button.set_css_classes([*self.common_btn_css_classes, 'destructive-action'])

        elif self.app_list_element.installed_status == InstalledStatus.UPDATING:
            self.primary_action_button.set_label(_('Updating'))

        elif self.app_list_element.installed_status == InstalledStatus.ERROR:
            self.primary_action_button.set_label(_('Error'))
            self.primary_action_button.set_css_classes([*self.common_btn_css_classes, 'destructive-action'])

    def provider_refresh_installed_status(self, status: Optional[InstalledStatus] = None, final=False):
        if status:
            self.app_list_element.installed_status = status

        self.update_installation_status()

    # Load the boxed list with additional information
    def load_extra_details(self):
        gtk_list = Gtk.ListBox(css_classes=['boxed-list'], margin_bottom=20)

        row = Adw.ActionRow(title=self.provider.name.capitalize(), subtitle='Package type')
        logging.info(self.provider.icon)
        row_img = Gtk.Image(resource=self.provider.icon, pixel_size=34)
        row.add_prefix(row_img)
        gtk_list.append(row)

        self.extra_data.append(gtk_list)

    def show_row_spinner(self, status: bool):
        self.desc_row_spinner.set_visible(status)
        self.desc_row_spinner.set_spinning(status)

    def set_trust_button(self, trusted=False):
        if trusted:
            self.trust_app_check_button_revealer.set_reveal_child(False)
            self.trust_app_check_button.set_active(True)
            self.secondary_action_button.set_sensitive(True),
            self.primary_action_button.set_sensitive(True)
        else:
            self.trust_app_check_button_revealer.set_reveal_child(True)
            self.trust_app_check_button.set_active(False)
            self.secondary_action_button.set_sensitive(False)
            self.primary_action_button.set_sensitive(False)

    def after_trust_buttons_interaction(self, widget):
        if self.trust_app_check_button.get_active():
            self.app_list_element.trusted = True

            self.trust_app_check_button_revealer.set_reveal_child(False)
            self.title.set_label('...')
            self.load(load_completed_callback=lambda: [
                self.secondary_action_button.set_sensitive(True),
                self.primary_action_button.set_sensitive(True)
            ])