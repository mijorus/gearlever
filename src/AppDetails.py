import time
import logging
import base64
import os
import shlex
from typing import Optional, Callable
from gi.repository import Gtk, GObject, Adw, Gdk, Gio, Pango, GLib

from .State import state
from .lib.terminal import sandbox_sh
from .models.UpdateManager import UpdateManager, UpdateManagerChecker
from .models.AppListElement import InstalledStatus
from .providers.AppImageProvider import AppImageListElement, AppImageUpdateLogic
from .providers.providers_list import appimage_provider
from .lib.async_utils import _async, idle, debounce
from .lib.json_config import read_json_config, set_json_config, read_config_for_app, save_config_for_app
from .lib.utils import url_is_valid, get_file_hash, get_application_window, show_message_dialog
from .components.CustomComponents import CenteringBox, LabelStart
from .components.AppDetailsConflictModal import AppDetailsConflictModal


class AppDetails(Gtk.ScrolledWindow):
    """The presentation screen for an application"""
    __gsignals__ = {
        "uninstalled-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    UPDATE_BTN_LABEL = _('Update')
    CANCEL_UPDATE = _('Cancel update')
    UPDATE_FETCHING = _('Checking updates...')
    UPDATE_NOT_AVAIL_BTN_LABEL = _('No updates available')
    UPDATE_INFO_EMBEDDED = _('This application includes update information provided by the developer')
    UPDATE_INFO_NOT_EMBEDDED = _('Manage update details for this application')


    def __init__(self):
        super().__init__()
        self.current_update_manager: Optional[UpdateManager] = None
        self.ACTION_ROW_ICON_SIZE = 34
        self.EXTRA_DATA_SPACING = 20

        self.app_list_element: AppImageListElement = None
        self.common_btn_css_classes = ['pill', 'text-button']

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=10, margin_bottom=10, margin_start=20, margin_end=20)

        # 1st row
        self.details_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.icon_slot = Gtk.Box()

        title_col = CenteringBox(orientation=Gtk.Orientation.VERTICAL, hexpand=True, spacing=2)
        self.title = Gtk.Label(label='', css_classes=['title-1'], hexpand=True, halign=Gtk.Align.CENTER, wrap=True)
        self.app_subtitle = Gtk.Label(
            label='',
            halign=Gtk.Align.CENTER,
            css_classes=['dim-label', 'subtitle'],
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=100,
            selectable=True,
        )

        [title_col.append(el) for el in [self.title, self.app_subtitle]]

        self.source_selector_hdlr = None
        self.source_selector = Gtk.ComboBoxText()
        self.source_selector_revealer = Gtk.Revealer(child=self.source_selector, transition_type=Gtk.RevealerTransitionType.CROSSFADE)

        # Action buttons
        self.primary_action_button = Gtk.Button(label='', valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, 
                                                css_classes=self.common_btn_css_classes, width_request=200)
        self.secondary_action_button = Gtk.Button(label='', valign=Gtk.Align.CENTER, 
                                            css_classes=self.common_btn_css_classes, width_request=200)
        self.update_action_button = Gtk.Button(
            label=_('Update'), 
            valign=Gtk.Align.CENTER, 
            width_request=200,
            css_classes=[*self.common_btn_css_classes, 'suggested-action'],
            visible=False
        )

        action_buttons_row = CenteringBox(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.primary_action_button.connect('clicked', self.on_primary_action_button_clicked)
        self.secondary_action_button.connect('clicked', self.on_secondary_action_button_clicked)
        self.update_action_button.connect('clicked', self.update_action_button_clicked)
        
        primary_action_buttons_row = CenteringBox(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        [primary_action_buttons_row.append(el) for el in [self.secondary_action_button, self.update_action_button]]
        [action_buttons_row.append(el) for el in [primary_action_buttons_row, self.primary_action_button]]

        [self.details_row.append(el) for el in [self.icon_slot, title_col, action_buttons_row]]

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
        [self.desc_row.append(el) for el in [self.desc_row_spinner, self.description]]

        # row
        self.third_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.extra_data = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.EXTRA_DATA_SPACING)
        self.third_row.append(self.extra_data)

        [self.main_box.append(el) for el in [self.details_row, self.previews_row, self.desc_row, self.third_row]]

        clamp = Adw.Clamp(child=self.main_box, maximum_size=600, margin_top=10, margin_bottom=20)

        # Window top banner
        self.window_banner = Adw.Banner(use_markup=True)
        self.window_banner.connect('button-clicked', self.after_trust_buttons_interaction)

        container_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        [container_box.append(el) for el in [self.window_banner, clamp]]

        self.env_variables_widgets = []
        self.env_variables_group_container = None
        self.save_vars_btn: Optional[Gtk.Button] = None

        # Update url entry
        self.update_url_group: Optional[Adw.PreferencesGroup] = None
        self.update_url_row: Optional[Adw.EntryRow] = None
        self.update_url_save_btn: Optional[Gtk.Button] = None
        self.update_url_source: Optional[Adw.ComboRow] = None
        self.update_url_group: Optional[Adw.PreferenciesGroup] = None

        self.set_child(container_box)

    def set_app_list_element(self, el: AppImageListElement):
        self.app_list_element = el
        self.provider = appimage_provider
        self.update_action_button.set_visible(False)

        self.load()

    def set_from_local_file(self, file: Gio.File):
        if appimage_provider.can_install_file(file):
            list_element = appimage_provider.create_list_element_from_file(file)

            self.set_app_list_element(list_element)
            return True

        logging.warn('Trying to open an unsupported file')
        return False

    @idle
    def complete_load(self, icon: Gtk.Image, generation: str, load_completed_callback: Optional[Callable] = None):
        self.show_row_spinner(True)

        self.details_row.remove(self.icon_slot)
        self.icon_slot = icon
        icon.set_pixel_size(128)

        self.details_row.prepend(self.icon_slot)
        self.title.set_label(self.app_list_element.name)

        self.app_subtitle.set_text(self.app_list_element.version)
        self.app_subtitle.set_visible(len(self.app_list_element.version))
        self.app_subtitle.set_selectable(self.app_list_element.installed_status is not InstalledStatus.INSTALLED)

        self.description.set_label(
            self.provider.get_description(self.app_list_element)
        )

        self.third_row.remove(self.extra_data)
        
        self.extra_data = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.EXTRA_DATA_SPACING)
        self.third_row.append(self.extra_data)

        self.install_button_label_info = None

        # Load the boxed list with additional information
        gtk_list = Gtk.ListBox(css_classes=['boxed-list'])

        # Package info
        gtk_list.append(self.create_package_info_row(generation))

        # The path of the executable
        gtk_list.append(self.create_exec_path_row())

        # Hashes
        if self.app_list_element.installed_status is not InstalledStatus.INSTALLED:
            gtk_list.append(self.create_app_hash_row())
        
        self.update_installation_status()

        system_arch = sandbox_sh(['arch'])

        if self.app_list_element.installed_status is InstalledStatus.INSTALLED:
            # Exec arguments
            gtk_list.append(self.create_show_exec_args_row())

            # A custom link to a website
            gtk_list.append(self.create_edit_custom_website_row())

            # Reload metadata row
            reload_data_listbox = Gtk.ListBox(css_classes=['boxed-list'])
            reload_data_listbox.append(self.create_reload_metadata_row())
            self.extra_data.prepend(reload_data_listbox)

            # Show or hide window banner
            if system_arch and system_arch != self.app_list_element.architecture:
                self.show_invalid_arch_banner()
            elif self.app_list_element.external_folder:
                self.window_banner.set_revealed(True)
                self.window_banner.set_button_label(None)
                self.window_banner.set_title(_('This app is located outside the default folder\n<small>You can hide external apps in the settings</small>'))
            else:
                self.window_banner.set_revealed(False)
        else:
            if self.app_list_element.trusted:
                if system_arch and system_arch != self.app_list_element.architecture:
                    self.show_invalid_arch_banner()
                else:
                    self.window_banner.set_revealed(False)
            else:
                self.window_banner.set_revealed(True)
                self.window_banner.set_title(_('Please, verify the source of this app before opening it'))
                self.window_banner.set_button_label(_('Unlock'))

            if not self.app_list_element.trusted:
                self.secondary_action_button.set_sensitive(False)
                self.primary_action_button.set_sensitive(False)

        self.extra_data.append(gtk_list)

        if self.app_list_element.installed_status is InstalledStatus.INSTALLED:
            self.update_url_group = self.create_edit_update_url_row()
            self.extra_data.append(self.update_url_group)

            edit_env_vars_widget = self.create_edit_env_vars_row()
            self.extra_data.append(edit_env_vars_widget)

            self.update_action_button.set_visible(False)
            self.check_updates()

        self.show_row_spinner(False)

        self.desc_row.set_visible(len(self.description.get_text()) > 0)

        if load_completed_callback:
            load_completed_callback()

    @_async
    def load(self, load_completed_callback: Optional[Callable] = None):
        self.show_row_spinner(True)
        icon = Gtk.Image(icon_name='application-x-executable-symbolic')
        generation = self.provider.get_appimage_type(self.app_list_element)


        if self.app_list_element.trusted:
            icon = self.provider.get_icon(self.app_list_element)

            if self.app_list_element.installed_status is not InstalledStatus.INSTALLED:
                self.provider.refresh_title(self.app_list_element)

        self.complete_load(
            icon,
            generation,
            load_completed_callback=load_completed_callback
        )

    @_async
    def install_file(self, el: AppImageListElement):
        try:
            self.provider.install_file(el)
        except Exception as e:
            logging.error(str(e))

        self.update_installation_status()

        self.complete_load(
            self.provider.get_icon(self.app_list_element),
            self.provider.get_appimage_type(self.app_list_element),
        )

    def on_conflict_modal_close(self, widget, data: str):
        if data == 'cancel':
            self.app_list_element.update_logic = None
            return

        self.app_list_element.update_logic = AppImageUpdateLogic[data]
        self.on_primary_action_button_clicked()

    def on_primary_action_button_clicked(self, button: Optional[Gtk.Button] = None):
        if self.app_list_element.installed_status == InstalledStatus.INSTALLED:
            self.show_remove_confirm_dialog()
        elif self.app_list_element.installed_status == InstalledStatus.NOT_INSTALLED:
            if self.provider.is_updatable(self.app_list_element) and not self.app_list_element.update_logic:
                confirm_modal = AppDetailsConflictModal(app_name=self.app_list_element.name)

                confirm_modal.modal.connect('response', self.on_conflict_modal_close)
                confirm_modal.modal.present()
                return

            self.app_list_element.set_installed_status(InstalledStatus.INSTALLING)

            if self.app_list_element.trusted:
                self.update_installation_status()

                if self.app_list_element.update_logic and (self.app_list_element.update_logic == AppImageUpdateLogic.REPLACE):
                    old_version = next(
                        filter(lambda old_v: (old_v.name == self.app_list_element.name), self.provider.list_installed()), 
                        None
                    )

                    self.app_list_element.updating_from = old_version
                    self.provider.uninstall(old_version)

                self.install_file(self.app_list_element)

        self.update_installation_status()

    def on_secondary_action_button_clicked(self, button: Gtk.Button):
        if self.app_list_element.installed_status in [InstalledStatus.INSTALLED, InstalledStatus.NOT_INSTALLED]:
            is_terminal = self.app_list_element.desktop_entry and self.app_list_element.desktop_entry.getTerminal()
            if self.app_list_element.trusted and (not is_terminal):
                try:
                    self.app_list_element.set_trusted()
                    
                    pre_launch_label = self.secondary_action_button.get_label()
                    self.secondary_action_button.set_label(_('Launching...'))
                    self.secondary_action_button.set_sensitive(False)

                    try:
                        self.provider.run(self.app_list_element)
                    except Exception as e:
                        logging.error(e)
                        show_message_dialog(_('Error'), str(e))

                    self.post_launch_animation(restore_as=pre_launch_label)

                except Exception as e:
                    logging.error(str(e))
        elif self.app_list_element.installed_status == InstalledStatus.UPDATING:
            if self.current_update_manager:
                self.current_update_manager.cancel_download()
                self.update_installation_status()

    def on_remove_app_clicked(self, dialog, response: str):
        if response == 'remove':
            self.app_list_element.set_installed_status(InstalledStatus.UNINSTALLING)
            self.update_installation_status()

            self.provider.uninstall(self.app_list_element)
            
            app_config = self.get_config_for_app()
            conf = read_json_config('apps')

            if 'b64name' in app_config and app_config['b64name'] in conf:
                del conf[app_config['b64name']]
                set_json_config('apps', conf)
            else:
                logging.warn('Missing app key from app config')

            self.emit('uninstalled-app', self)

    @_async
    def post_launch_animation(self, restore_as):
        GLib.idle_add(lambda: self.secondary_action_button.set_sensitive(False))
        time.sleep(3)

        GLib.idle_add(lambda: self.secondary_action_button.set_label(restore_as))
        GLib.idle_add(lambda: self.secondary_action_button.set_sensitive(True))

    @_async
    def update_action_button_clicked(self, w):
        self.app_list_element.set_installed_status(InstalledStatus.UPDATING)
        self.update_installation_status()

        app_conf = self.get_config_for_app()
        manager = UpdateManagerChecker.check_url_for_app(self.app_list_element)

        if not manager:
            return

        try:
            self.current_update_manager = manager
            self.app_list_element = appimage_provider.update_from_url(manager, self.app_list_element, status_cb= lambda s: \
                GLib.idle_add(lambda: self.update_action_button.set_label(str(round(s * 100)) + ' %')
            ))
        except Exception as e:
            self.show_update_error_dialog(str(e))

        self.app_list_element.set_installed_status(InstalledStatus.INSTALLED)
        self.current_update_manager = None
        manager.cleanup()

        GLib.idle_add(lambda: self.update_action_button.set_label(_('Update')))
        self.check_updates()

        self.provider.reload_metadata(self.app_list_element)

        icon = self.provider.get_icon(self.app_list_element)
        self.provider.refresh_title(self.app_list_element)

        generation = self.provider.get_appimage_type(self.app_list_element)
        self.complete_load(icon, generation)
        self.update_installation_status()

    @idle
    def show_update_error_dialog(self, msg: str):
        logging.error(msg)
        dialog = Adw.MessageDialog(
            transient_for=get_application_window(),
            heading=_('Update error'),
            body=msg
        )

        dialog.add_response('okay', _('Close'))

        dialog.present()

    @idle
    def show_remove_confirm_dialog(self):
        dialog = Adw.MessageDialog(
            transient_for=get_application_window(),
            heading=_('Do you really want to remove this app?'),
        )

        dialog.add_response('cancel', _('Cancel'))
        dialog.add_response('remove', _('Remove'))
        dialog.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response('cancel')
        dialog.set_close_response('remove')
        dialog.connect('response', self.on_remove_app_clicked)

        dialog.present()

    @idle
    def set_all_btn_sensitivity(self, s: bool):
        self.primary_action_button.set_sensitive(s)
        self.secondary_action_button.set_sensitive(s)
        self.update_action_button.set_sensitive(s)

    @idle
    def restore_launch_button(self, restore_as):
        self.secondary_action_button.set_label(restore_as)
        self.secondary_action_button.set_sensitive(True)

    def update_status_callback(self, status: bool):
        if not status:
            self.app_list_element.set_installed_status(InstalledStatus.ERROR)

        self.update_installation_status()

    def update_installation_status(self):
        self.primary_action_button.set_css_classes(self.common_btn_css_classes)
        self.secondary_action_button.set_css_classes(self.common_btn_css_classes)
        self.source_selector.set_visible(False)

        self.primary_action_button.set_sensitive(True)
        self.secondary_action_button.set_sensitive(True)

        if self.app_list_element.installed_status == InstalledStatus.INSTALLED:
            if self.app_list_element.desktop_entry and self.app_list_element.desktop_entry.getTerminal():
                self.secondary_action_button.set_label(_('This app runs in the terminal'))
            else:
                self.secondary_action_button.set_label(_('Launch'))

            self.primary_action_button.set_label(_('Remove'))
            self.primary_action_button.set_css_classes([*self.common_btn_css_classes, 'destructive-action'])

        elif self.app_list_element.installed_status == InstalledStatus.UNINSTALLING:
            self.primary_action_button.set_label(_('Uninstalling...'))
            self.primary_action_button.set_sensitive(False)

        elif self.app_list_element.installed_status == InstalledStatus.INSTALLING:
            self.primary_action_button.set_label(_('Installing...'))
            self.primary_action_button.set_sensitive(False)

        elif self.app_list_element.installed_status == InstalledStatus.NOT_INSTALLED:
            if not self.app_list_element.desktop_entry:
                self.secondary_action_button.set_label(_('Launch'))
            else:
                if self.app_list_element.desktop_entry.getTerminal():
                    self.secondary_action_button.set_label(_('This app runs in the terminal'))
                    self.secondary_action_button.set_sensitive(False)
                else:
                    self.secondary_action_button.set_label(_('Launch'))

            self.primary_action_button.set_label(_('Move to the app menu'))
            self.primary_action_button.set_css_classes([*self.common_btn_css_classes, 'suggested-action'])

        elif self.app_list_element.installed_status == InstalledStatus.UPDATE_AVAILABLE:
            pass
        elif self.app_list_element.installed_status == InstalledStatus.UPDATING:
            self.primary_action_button.set_sensitive(False)
            self.secondary_action_button.set_label(self.CANCEL_UPDATE)
            self.secondary_action_button.set_sensitive(True)
            self.secondary_action_button.set_css_classes([*self.common_btn_css_classes])
            self.update_action_button.set_sensitive(False)

        elif self.app_list_element.installed_status == InstalledStatus.ERROR:
            self.primary_action_button.set_label(_('Error'))
            self.primary_action_button.set_css_classes([*self.common_btn_css_classes, 'destructive-action'])

    def provider_refresh_installed_status(self, status: Optional[InstalledStatus] = None):
        if status:
            self.app_list_element.installed_status = status

        self.update_installation_status()

    def show_invalid_arch_banner(self):
        self.window_banner.set_revealed(True)
        self.window_banner.set_title(_('This app might not be compatible with your system architecture'))
        self.window_banner.set_button_label('')

    @idle
    def show_row_spinner(self, status: bool):
        self.desc_row_spinner.set_visible(status)
        self.desc_row_spinner.set_spinning(status)

    def after_trust_buttons_interaction(self, widget: Adw.Banner):
        if not self.app_list_element:
            return
        
        self.app_list_element.trusted = True
        widget.set_revealed(False)

        self.title.set_label('...')
        self.load()

    @debounce(0.5)
    @idle
    def on_web_browser_input_apply(self, widget):
        app_conf = self.get_config_for_app()

        text = widget.get_text().strip()

        widget.remove_css_class('error')
        if text and (not url_is_valid(text)):
            return widget.add_css_class('error')

        if text:
            widget.add_css_class('success')
        else:
            widget.remove_css_class('success')
            widget.remove_css_class('error')

        app_conf['website'] = text
        save_config_for_app(app_conf)

    @idle
    def set_app_as_updatable(self):
        self.update_action_button.set_visible(True)
        self.update_action_button.set_label(self.UPDATE_FETCHING)
        self.update_action_button.set_sensitive(False)

    @idle
    def set_update_information(self, manager: UpdateManager):
        if manager.embedded:
            self.update_url_row.set_text(manager.url)
            self.update_url_source.set_selected(
                self.update_url_source.get_model()._items_val.index(manager.label)
            )
        
        self.update_url_row.set_editable(not manager.embedded)
        self.update_url_source.set_sensitive(not manager.embedded)
        self.update_url_save_btn.set_visible(not manager.embedded)

        if manager.embedded:
            self.update_url_group.set_description(self.UPDATE_INFO_EMBEDDED)
        else:
            self.update_url_group.set_description(self.UPDATE_INFO_NOT_EMBEDDED)

    @_async
    def check_updates(self):
        manager = UpdateManagerChecker.check_url_for_app(self.app_list_element)

        if not manager:
            GLib.idle_add(lambda: self.update_url_save_btn.set_visible(True))
            return

        self.set_app_as_updatable()
        self.set_update_information(manager)

        is_updatable = manager.is_update_available(self.app_list_element)
        self.app_list_element.is_updatable_from_url = is_updatable

        if is_updatable:
            logging.debug(f'{self.app_list_element.name} is_updatable')
            GLib.idle_add(lambda: self.update_action_button.set_label(self.UPDATE_BTN_LABEL))
        else:
            GLib.idle_add(lambda: self.update_action_button.set_label(self.UPDATE_NOT_AVAIL_BTN_LABEL))

        GLib.idle_add(lambda: self.update_action_button.set_sensitive(True))
        GLib.idle_add(lambda: self.update_action_button.set_sensitive(is_updatable))

    def on_app_update_url_change(self, *props):
        app_conf = self.get_config_for_app()
        has_changed = False

        manager_label = self.update_url_source.get_model().get_string(
            self.update_url_source.get_selected())
    
        selected_manager = list(filter(lambda m: m.label == manager_label, 
                                  UpdateManagerChecker.get_models()))[0]
        
        if app_conf.get('update_url_manager', None) != selected_manager.name:
            has_changed = True

        if app_conf.get('update_url', None) != self.update_url_row.get_text():
            has_changed = True

        self.update_url_save_btn.set_sensitive(has_changed)

    @_async
    def on_app_update_url_apply(self, ev):
        app_conf = self.get_config_for_app()
        widget = self.update_url_row

        text = widget.get_text().strip()

        GLib.idle_add(lambda: widget.remove_css_class('error'))
        GLib.idle_add(lambda: widget.remove_css_class('success'))

        if text:
            manager_label = self.update_url_source.get_model().get_string(
            self.update_url_source.get_selected())
    
            selected_manager = list(filter(lambda m: m.label == manager_label, 
                                    UpdateManagerChecker.get_models()))[0]

            manager = UpdateManagerChecker.check_url(text, model=selected_manager)
            if not manager:
                GLib.idle_add(lambda: widget.add_css_class('error'))
                return
            
            app_conf['update_url'] = manager.url
            app_conf['update_url_manager'] = manager.name
        else:
            if 'update_url' in app_conf:
                del app_conf['update_url']
            
            if 'update_url_manager' in app_conf:
                del app_conf['update_url_manager']
        
        save_config_for_app(app_conf)
        GLib.idle_add(lambda: widget.add_css_class('success'))

    def on_env_var_value_changed(self, widget, key_widget, value_widget):
        key = key_widget.get_text()
        value_widget.set_sensitive(len(key) > 0)
        key_widget.remove_css_class('error')

        if not key:
            return
        
        counts = 0
        for kv_widgets in self.env_variables_widgets:
            k, v = kv_widgets
            
            if k.get_text() == key_widget.get_text():
                counts += 1

        if counts > 1:
            key_widget.add_css_class('error')
        
        value_widget.set_sensitive(counts == 1)
        self.save_vars_btn.set_sensitive(counts == 1)

    def on_save_env_vars_clicked(self, widget):
        widget.set_sensitive(False)
        self.update_env_variables()
        self.provider.update_desktop_file(self.app_list_element)

    def on_delete_env_var_clicked(self, widget, key_widget, value_widget, listbox):
        for i, kv_widgets in enumerate(self.env_variables_widgets):
            k, v = kv_widgets
            
            if k.get_text() == key_widget.get_text():
                self.env_variables_widgets.pop(i)
                break

        self.update_env_variables()
        self.provider.update_desktop_file(self.app_list_element)

        if self.env_variables_group_container:
            self.env_variables_group_container.remove(listbox)

    @debounce(0.5)
    @idle
    def on_cmd_arguments_changed(self, widget):
        text = widget.get_text().strip()
        text = text.replace('\n', '')

        self.app_list_element.exec_arguments = shlex.split(text)
        self.provider.update_desktop_file(self.app_list_element)

    # Returns the configuration from the json for this specific app
    def get_config_for_app(self) -> dict:
        return read_config_for_app(self.app_list_element)

    def on_web_browser_open_btn_clicked(self, widget):
        app_config = self.get_config_for_app()

        if ('website' in app_config) and url_is_valid(app_config['website']):
            launcher = Gtk.UriLauncher.new(app_config['website'])
            launcher.launch()

    def on_update_url_info_btn_clicked(self, widget):
        url = 'https://mijorus.it/posts/gearlever/update-url-info/'
        launcher = Gtk.UriLauncher.new(url)
        launcher.launch()

    @_async
    def on_refresh_metadata_btn_clicked(self, widget):
        self.show_row_spinner(True)
        GLib.idle_add(lambda: widget.set_sensitive(False))

        self.provider.reload_metadata(self.app_list_element)

        icon = self.provider.get_icon(self.app_list_element)
        self.provider.refresh_title(self.app_list_element)

        generation = self.provider.get_appimage_type(self.app_list_element)

        self.complete_load(icon, generation)

    def on_open_folder_clicked(self, widget):
        path = Gio.File.new_for_path(os.path.dirname(self.app_list_element.file_path))
        launcher = Gtk.FileLauncher.new(path)
        launcher.launch()

    def update_env_variables(self):
        self.app_list_element.env_variables = []
        for kv_widgets in self.env_variables_widgets:
            k, v = kv_widgets

            if k.has_css_class('error') or v.has_css_class('error'):
                continue

            key = k.get_text().strip()
            value = v.get_text().strip()
            value = shlex.quote(value)

            if key:
                self.app_list_element.env_variables.append(f'{key}={value}')

    def on_create_edit_row_btn_clicked(self, w):
        edit_form = self.create_edit_env_var_form()
        self.env_variables_group_container.append(edit_form)

    # Create widgets methods

    def create_edit_custom_website_row(self) -> Adw.EntryRow:
        app_config = self.get_config_for_app()
            
        row = Adw.EntryRow(
            title=(_('Website') if ('website' in app_config and app_config['website']) else _('Add a website')),
            selectable=False,
            text=(app_config['website'] if 'website' in app_config else '')
        )

        row_img = Gtk.Image(icon_name='gl-earth', pixel_size=self.ACTION_ROW_ICON_SIZE)
        row_btn = Gtk.Button(
            icon_name='gl-arrow2-top-right-symbolic', 
            valign=Gtk.Align.CENTER, 
            tooltip_text=_('Open URL'),
        )
        
        row_btn.connect('clicked', self.on_web_browser_open_btn_clicked)

        row.connect('changed', self.on_web_browser_input_apply)
        row.add_prefix(row_img)
        row.add_suffix(row_btn)

        return row

    def create_edit_update_url_row(self) -> Adw.EntryRow:
        app_config = self.get_config_for_app()

        save_btn_content = Adw.ButtonContent(
            icon_name='gearlever-check-plain-symbolic',
            label=_('Save')
        )

        self.update_url_save_btn = Gtk.Button(child=save_btn_content, sensitive=False,
                                        css_classes=['suggested-action'])

        self.update_url_save_btn.connect('clicked', self.on_app_update_url_apply)

        btn_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5, 
                                valign=Gtk.Align.CENTER)
        btn_container.append(self.update_url_save_btn)

        group = Adw.PreferencesGroup(
            title=_('Update management'),
            description=self.UPDATE_INFO_NOT_EMBEDDED,
            header_suffix=btn_container,
        )

        title = _('Update URL')

        combo_model = Gtk.StringList()
        combo_model._items_val = []
        selected_model = app_config.get('update_url_manager', None)

        self.update_url_source = Adw.ComboRow(
            title=_('Source'),
            subtitle=_('Select the source type'),
            model=combo_model
        )

        for i, m in enumerate(UpdateManagerChecker.get_models()):
            combo_model.append(m.label)
            combo_model._items_val.append(m.label)

            if selected_model == m.name:
                self.update_url_source.set_selected(i)

        self.update_url_row = Adw.EntryRow(
            title=title,
            selectable=True,
            text=(app_config.get('update_url', ''))
        )

        row_img = Gtk.Image(icon_name='gl-software-update-available-symbolic', 
                            pixel_size=self.ACTION_ROW_ICON_SIZE)

        row_btn = Gtk.Button(
            icon_name='gl-info-symbolic', 
            valign=Gtk.Align.CENTER, 
            tooltip_text=_('How it works'),
        )

        row_btn.connect('clicked', self.on_update_url_info_btn_clicked)
        self.update_url_source.connect('notify::selected', self.on_app_update_url_change)
        self.update_url_row.connect('changed', self.on_app_update_url_change)

        self.update_url_row.add_prefix(row_img)
        self.update_url_row.add_suffix(row_btn)

        group.add(self.update_url_source)
        group.add(self.update_url_row)

        return group
    
    def create_reload_metadata_row(self) -> Adw.EntryRow:
        row = Adw.ActionRow(selectable=False, activatable=True,
            title=(_('Reload metadata')), 
            subtitle=_('Update information like icon, version and description.\nUseful if the app updated itself.')
        )

        row_img = Gtk.Image(icon_name='gl-refresh', pixel_size=self.ACTION_ROW_ICON_SIZE)

        row.add_prefix(row_img)
        row.connect('activated', self.on_refresh_metadata_btn_clicked)

        return row
    
    def create_show_exec_args_row(self) -> Adw.ActionRow:
        row = Adw.EntryRow(
            title=(_('Command line arguments')),
            selectable=False,
            text=' '.join(self.app_list_element.exec_arguments)
        )

        row_img = Gtk.Image(icon_name='gearlever-cmd-args', pixel_size=self.ACTION_ROW_ICON_SIZE)
        row.connect('changed', self.on_cmd_arguments_changed)
        row.add_prefix(row_img)

        return row

    def create_app_hash_row(self) -> Adw.ActionRow:
        md5_hash = get_file_hash(Gio.File.new_for_path(self.app_list_element.file_path))
        sha1_hash = get_file_hash(Gio.File.new_for_path(self.app_list_element.file_path), 'sha1')
        sha256_hash = get_file_hash(Gio.File.new_for_path(self.app_list_element.file_path), 'sha256')

        row = Adw.ActionRow(
            subtitle=f'md5: {md5_hash}\nsha1: {sha1_hash}\nsha256: {sha256_hash}', 
            title=_('Hash'),
            selectable=True
        )

        row_img = Gtk.Image(icon_name='gl-hash-symbolic', pixel_size=self.ACTION_ROW_ICON_SIZE)
        row.add_prefix(row_img)

        return row
    
    def create_exec_path_row(self) -> Adw.ActionRow:
        row = Adw.ActionRow(title=_('Path'), subtitle=self.app_list_element.file_path, subtitle_selectable=True, selectable=False)
        row_img = Gtk.Image(icon_name='gearlever-file-manager-symbolic', pixel_size=self.ACTION_ROW_ICON_SIZE)
        row_btn = Gtk.Button(icon_name='gl-arrow2-top-right-symbolic', valign=Gtk.Align.CENTER, tooltip_text=_('Open Folder'))
        row_btn.connect('clicked', self.on_open_folder_clicked)
        row.add_prefix(row_img)
        row.add_suffix(row_btn)

        return row

    def create_package_info_row(self, gen) -> Adw.ActionRow:
        row = Adw.ActionRow(
            subtitle=f'{self.provider.name.capitalize()} Type. {gen}', 
            title=_('Package type'),
            selectable=False
        )

        row_img = Gtk.Image(resource=self.provider.icon, pixel_size=self.ACTION_ROW_ICON_SIZE)
        row.add_prefix(row_img)

        return row
    
    def create_edit_env_var_form(self, key='', value=''):
        listbox = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            halign=Gtk.Align.CENTER,
            spacing=10,
            margin_top=self.EXTRA_DATA_SPACING / 2,
            margin_bottom=self.EXTRA_DATA_SPACING / 2,
        )

        row_key = Gtk.Entry(placeholder_text=_('Key'), text=key, hexpand=True)
        row_value = Gtk.Entry(placeholder_text=_('Value'), text=value, hexpand=True, sensitive=(len(key) > 0))
        delete_btn = Gtk.Button(icon_name='gl-user-trash-symbolic', css_classes=['destructive-action'])

        row_key.connect('changed', self.on_env_var_value_changed, row_key, row_value)
        row_value.connect('changed', self.on_env_var_value_changed, row_key, row_value)
        delete_btn.connect('clicked', self.on_delete_env_var_clicked, row_key, row_value, listbox)

        listbox.append(row_key)
        listbox.append(Gtk.Label.new('='))
        listbox.append(row_value)
        listbox.append(delete_btn)

        self.env_variables_widgets.append([row_key, row_value])

        return listbox
    
    def create_edit_env_vars_row(self) -> Adw.PreferencesGroup:
        add_btn_content = Adw.ButtonContent(
            icon_name='gl-plus-symbolic',
            label=_('Add')
        )

        save_btn_content = Adw.ButtonContent(
            icon_name='gearlever-check-plain-symbolic',
            label=_('Save')
        )

        add_item_btn = Gtk.Button(child=add_btn_content)
        self.save_vars_btn = Gtk.Button(child=save_btn_content, sensitive=False,
                                        css_classes=['suggested-action'])

        self.save_vars_btn.connect('clicked', self.on_save_env_vars_clicked)

        btn_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5, 
                                valign=Gtk.Align.CENTER)

        [btn_container.append(w) for w in [self.save_vars_btn, add_item_btn]]

        group = Adw.PreferencesGroup(
            title=_('Environment variables'),
            description=_('Add or customize environment for this application'),
            header_suffix=btn_container,
        )

        self.env_variables_group_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            css_classes=['card'],
            margin_top=self.EXTRA_DATA_SPACING / 2
        )

        group.add(self.env_variables_group_container)

        add_item_btn.connect('clicked', self.on_create_edit_row_btn_clicked)

        self.env_variables_widgets = []
        for kv in self.app_list_element.env_variables:
            k, v = kv.split('=', 1)

            row = self.create_edit_env_var_form(k, v)
            self.env_variables_group_container.append(row)

        return group
