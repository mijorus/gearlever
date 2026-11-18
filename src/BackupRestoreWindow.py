import os
import logging
from datetime import datetime
from typing import List, Dict, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib, Pango

from .lib.backup_manager import BackupManager
from .providers.providers_list import appimage_provider
from .models.Settings import Settings
from .lib.utils import gnu_naturalsize, show_message_dialog
from .lib.async_utils import _async, idle


class BackupRestoreWindow(Adw.Window):
    def __init__(self, parent_window=None, **kwargs):
        super().__init__(**kwargs)
        self.parent_window = parent_window
        self.set_title(_("Backup & Restore"))
        self.set_default_size(680, 720)
        self.set_modal(True)
        if parent_window:
            self.set_transient_for(parent_window)

        self.settings = Settings.settings
        self.installed_apps = []
        self.backup_app_rows = []

        # Restore state
        self.inspect_data: Optional[Dict] = None
        self.loaded_backup_path: Optional[str] = None
        self.restore_app_rows = []
        self.restore_dest_folder = self.settings.get_string('appimages-default-folder') or os.path.expanduser('~/Applications')

        # Main UI layout
        self.toast_overlay = Adw.ToastOverlay()
        self.toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(self.toolbar_view)
        self.set_content(self.toast_overlay)

        # Header bar
        self.header_bar = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()
        self.view_switcher_title = Adw.ViewSwitcherTitle(stack=self.view_stack)
        self.header_bar.set_title_widget(self.view_switcher_title)
        self.toolbar_view.add_top_bar(self.header_bar)

        # Build Backup Page
        self.build_backup_page()

        # Build Restore Page
        self.build_restore_page()

        self.toolbar_view.set_content(self.view_stack)

        # Load installed apps for backup page
        self.load_installed_apps()

    def build_backup_page(self):
        self.backup_page = Adw.PreferencesPage()

        # Group 1: Options
        options_group = Adw.PreferencesGroup(
            title=_("Backup Options"),
            description=_("Choose what components to include in the backup archive")
        )

        self.include_binaries_row = Adw.SwitchRow(
            title=_("Include AppImage executables"),
            subtitle=_("Backs up the full .AppImage binaries. Uncheck for a lightweight configuration-only backup."),
            active=True
        )

        self.include_app_data_row = Adw.SwitchRow(
            title=_("Include application data & settings"),
            subtitle=_("Backs up configuration and data directories (e.g. in ~/.config or portable .home/.config folders)"),
            active=True
        )

        self.include_gearlever_row = Adw.SwitchRow(
            title=_("Include Gear Lever configurations"),
            subtitle=_("Backs up update URLs, custom names, terminal flags, and system launchers"),
            active=True
        )

        options_group.add(self.include_binaries_row)
        options_group.add(self.include_app_data_row)
        options_group.add(self.include_gearlever_row)
        self.backup_page.add(options_group)

        # Group 2: Applications selection
        self.apps_group = Adw.PreferencesGroup(
            title=_("Select Applications"),
            description=_("Choose which installed applications to back up")
        )

        # Select all / Deselect all buttons header
        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_bottom=6)
        self.select_all_btn = Gtk.Button(label=_("Select All"), css_classes=["flat"])
        self.select_all_btn.connect('clicked', lambda _: self.set_all_backup_selection(True))
        self.deselect_all_btn = Gtk.Button(label=_("Deselect All"), css_classes=["flat"])
        self.deselect_all_btn.connect('clicked', lambda _: self.set_all_backup_selection(False))

        self.selection_count_label = Gtk.Label(
            label="",
            hexpand=True,
            halign=Gtk.Align.END,
            css_classes=["dim-label"]
        )

        buttons_box.append(self.select_all_btn)
        buttons_box.append(self.deselect_all_btn)
        buttons_box.append(self.selection_count_label)
        self.apps_group.set_header_suffix(buttons_box)

        self.backup_page.add(self.apps_group)

        # Group 3: Progress & Action
        action_group = Adw.PreferencesGroup()
        action_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=10, margin_bottom=20)

        self.backup_progress_bar = Gtk.ProgressBar(visible=False, show_text=True)
        self.backup_status_label = Gtk.Label(label="", visible=False, css_classes=["dim-label"])

        self.create_backup_btn = Gtk.Button(
            label=_("Create Backup..."),
            css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER
        )
        self.create_backup_btn.connect('clicked', self.on_create_backup_clicked)

        action_box.append(self.backup_progress_bar)
        action_box.append(self.backup_status_label)
        action_box.append(self.create_backup_btn)
        action_group.add(action_box)
        self.backup_page.add(action_group)

        self.view_stack.add_titled_with_icon(
            self.backup_page,
            "backup",
            _("Backup"),
            "document-save-symbolic"
        )

    def build_restore_page(self):
        self.restore_page = Adw.PreferencesPage()

        # Group 1: File selection
        file_group = Adw.PreferencesGroup(
            title=_("Backup Archive"),
            description=_("Select a .glbackup or .tar.gz archive created with Gear Lever")
        )

        self.select_file_row = Adw.ActionRow(
            title=_("No backup archive selected"),
            subtitle=_("Choose a backup file from your disk")
        )

        choose_file_btn = Gtk.Button(
            icon_name="document-open-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=_("Choose backup file")
        )
        choose_file_btn.connect('clicked', self.on_choose_backup_file_clicked)
        self.select_file_row.add_suffix(choose_file_btn)
        file_group.add(self.select_file_row)
        self.restore_page.add(file_group)

        # Group 2: Destination Folder & Options
        self.restore_options_group = Adw.PreferencesGroup(
            title=_("Restore Settings"),
            visible=False
        )

        self.restore_dest_row = Adw.ActionRow(
            title=_("AppImages destination folder"),
            subtitle=self.restore_dest_folder
        )
        choose_dest_btn = Gtk.Button(
            icon_name="gearlever-file-manager-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=_("Select folder")
        )
        choose_dest_btn.connect('clicked', self.on_choose_restore_folder_clicked)
        self.restore_dest_row.add_suffix(choose_dest_btn)

        self.restore_app_data_switch = Adw.SwitchRow(
            title=_("Restore application data & settings"),
            subtitle=_("Restores application configuration to ~/.config and portable folders"),
            active=True
        )

        self.restore_options_group.add(self.restore_dest_row)
        self.restore_options_group.add(self.restore_app_data_switch)
        self.restore_page.add(self.restore_options_group)

        # Group 3: Apps found in backup
        self.restore_apps_group = Adw.PreferencesGroup(
            title=_("Applications in Backup"),
            description=_("Choose which applications you want to restore"),
            visible=False
        )

        restore_buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_bottom=6)
        self.restore_select_all_btn = Gtk.Button(label=_("Select All"), css_classes=["flat"])
        self.restore_select_all_btn.connect('clicked', lambda _: self.set_all_restore_selection(True))
        self.restore_deselect_all_btn = Gtk.Button(label=_("Deselect All"), css_classes=["flat"])
        self.restore_deselect_all_btn.connect('clicked', lambda _: self.set_all_restore_selection(False))

        self.restore_selection_count_label = Gtk.Label(
            label="",
            hexpand=True,
            halign=Gtk.Align.END,
            css_classes=["dim-label"]
        )

        restore_buttons_box.append(self.restore_select_all_btn)
        restore_buttons_box.append(self.restore_deselect_all_btn)
        restore_buttons_box.append(self.restore_selection_count_label)
        self.restore_apps_group.set_header_suffix(restore_buttons_box)

        self.restore_page.add(self.restore_apps_group)

        # Group 4: Restore Action
        self.restore_action_group = Adw.PreferencesGroup(visible=False)
        action_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=10, margin_bottom=20)

        self.restore_progress_bar = Gtk.ProgressBar(visible=False, show_text=True)
        self.restore_status_label = Gtk.Label(label="", visible=False, css_classes=["dim-label"])

        self.perform_restore_btn = Gtk.Button(
            label=_("Restore Selected Applications"),
            css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER
        )
        self.perform_restore_btn.connect('clicked', self.on_perform_restore_clicked)

        action_box.append(self.restore_progress_bar)
        action_box.append(self.restore_status_label)
        action_box.append(self.perform_restore_btn)
        self.restore_action_group.add(action_box)
        self.restore_page.add(self.restore_action_group)

        self.view_stack.add_titled_with_icon(
            self.restore_page,
            "restore",
            _("Restore"),
            "document-revert-symbolic"
        )

    def load_installed_apps(self):
        self.installed_apps = appimage_provider.list_installed()
        self.backup_app_rows.clear()

        # Clear existing rows if any
        if not self.installed_apps:
            row = Adw.ActionRow(
                title=_("No installed applications found"),
                subtitle=_("Integrate some AppImages with Gear Lever first")
            )
            self.apps_group.add(row)
            self.create_backup_btn.set_sensitive(False)
            return

        for app in self.installed_apps:
            row = Adw.ActionRow(title=app.name)

            # Subtitle with path & size
            sub_parts = []
            if app.file_path and os.path.exists(app.file_path):
                sub_parts.append(gnu_naturalsize(os.path.getsize(app.file_path)))

            # Check app data
            app_data_list = BackupManager.detect_app_data(app)
            if app_data_list:
                data_labels = [d["label"] for d in app_data_list]
                sub_parts.append(f"Data: {', '.join(data_labels)}")

            if sub_parts:
                row.set_subtitle(" · ".join(sub_parts))

            # Prefix: CheckButton
            check = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
            check.connect('toggled', lambda _: self.update_backup_selection_count())
            row.add_prefix(check)

            # Icon
            try:
                icon_img = appimage_provider.get_icon(app)
                icon_img.set_pixel_size(32)
                row.add_prefix(icon_img)
            except Exception:
                pass

            self.apps_group.add(row)
            self.backup_app_rows.append({"app": app, "check": check, "row": row})

        self.update_backup_selection_count()

    def update_backup_selection_count(self):
        selected_count = sum(1 for item in self.backup_app_rows if item["check"].get_active())
        total = len(self.backup_app_rows)
        self.selection_count_label.set_label(f"{selected_count} / {total} " + _("selected"))
        self.create_backup_btn.set_sensitive(selected_count > 0)

    def set_all_backup_selection(self, select: bool):
        for item in self.backup_app_rows:
            item["check"].set_active(select)
        self.update_backup_selection_count()

    def on_create_backup_clicked(self, widget):
        selected_apps = [item["app"] for item in self.backup_app_rows if item["check"].get_active()]
        if not selected_apps:
            return

        dialog = Gtk.FileDialog(title=_("Save Backup Archive"), modal=True)
        default_name = f"gearlever-backup-{datetime.now().strftime('%Y-%m-%d')}.glbackup"
        dialog.set_initial_name(default_name)

        dialog.save_file(
            parent=self,
            cancellable=None,
            callback=self.on_save_backup_file_response,
            user_data=selected_apps
        )

    def on_save_backup_file_response(self, dialog, result, selected_apps):
        try:
            target_gfile = dialog.save_file_finish(result)
            output_path = target_gfile.get_path()
        except Exception as e:
            logging.info(f"Backup save cancelled: {e}")
            return

        # Start backup process
        self.create_backup_btn.set_sensitive(False)
        self.backup_progress_bar.set_visible(True)
        self.backup_status_label.set_visible(True)
        self.backup_progress_bar.set_fraction(0.0)

        include_binaries = self.include_binaries_row.get_active()
        include_app_data = self.include_app_data_row.get_active()
        include_gearlever = self.include_gearlever_row.get_active()

        self._run_backup_async(selected_apps, output_path, include_binaries, include_app_data, include_gearlever)

    @_async
    def _run_backup_async(self, apps, path, binaries, app_data, gearlever_config):
        def on_progress(cur, total, status_text):
            fraction = cur / max(total, 1)
            self._update_backup_progress(fraction, status_text)

        try:
            manifest = BackupManager.create_backup(
                selected_apps=apps,
                output_file_path=path,
                include_binaries=binaries,
                include_app_data=app_data,
                include_gearlever_config=gearlever_config,
                progress_callback=on_progress
            )
            self._on_backup_finished(True, path, len(manifest.get("apps", [])))
        except Exception as e:
            logging.error(f"Backup failed: {e}")
            self._on_backup_finished(False, str(e), 0)

    @idle
    def _update_backup_progress(self, fraction, text):
        self.backup_progress_bar.set_fraction(fraction)
        self.backup_status_label.set_label(text)

    @idle
    def _on_backup_finished(self, success, result_info, app_count):
        self.create_backup_btn.set_sensitive(True)
        self.backup_progress_bar.set_visible(False)
        self.backup_status_label.set_visible(False)

        if success:
            toast = Adw.Toast.new(_("Backup created successfully!"))
            self.toast_overlay.add_toast(toast)

            msg = _("Successfully backed up {count} applications to:\n{path}").format(
                count=app_count, path=result_info
            )
            show_message_dialog(msg, header=_("Backup Complete"))
        else:
            show_message_dialog(
                _("An error occurred during backup creation:\n") + result_info,
                header=_("Backup Failed")
            )

    # --- Restore Handlers ---
    def on_choose_backup_file_clicked(self, widget):
        dialog = Gtk.FileDialog(title=_("Select Backup Archive"), modal=True)

        filters = Gio.ListStore.new(Gtk.FileFilter)
        f_gl = Gtk.FileFilter()
        f_gl.set_name(_("Gear Lever Backups (*.glbackup, *.tar.gz)"))
        f_gl.add_pattern("*.glbackup")
        f_gl.add_pattern("*.tar.gz")
        f_gl.add_pattern("*.tgz")
        filters.append(f_gl)

        f_all = Gtk.FileFilter()
        f_all.set_name(_("All Files"))
        f_all.add_pattern("*")
        filters.append(f_all)

        dialog.set_filters(filters)

        dialog.open(
            parent=self,
            cancellable=None,
            callback=self.on_open_backup_file_response
        )

    def on_open_backup_file_response(self, dialog, result):
        try:
            selected_file = dialog.open_finish(result)
            archive_path = selected_file.get_path()
        except Exception as e:
            logging.info(f"Open backup cancelled: {e}")
            return

        try:
            inspect_data = BackupManager.inspect_backup(archive_path)
            self.loaded_backup_path = archive_path
            self.inspect_data = inspect_data
            self.load_backup_contents(inspect_data)
        except Exception as e:
            show_message_dialog(
                _("Invalid or corrupted backup archive:\n") + str(e),
                header=_("Error Reading Backup")
            )

    def load_backup_contents(self, manifest: Dict):
        file_name = os.path.basename(self.loaded_backup_path or "")
        created_at = manifest.get("created_at", _("Unknown"))
        if "T" in created_at:
            created_at = created_at.replace("T", " ").split(".")[0]

        apps = manifest.get("apps", [])
        self.select_file_row.set_title(file_name)
        self.select_file_row.set_subtitle(
            _("Created: {date} · Applications: {count}").format(date=created_at, count=len(apps))
        )

        # Clear previous rows from restore apps group
        for item in self.restore_app_rows:
            self.restore_apps_group.remove(item["row"])
        self.restore_app_rows.clear()

        # Add rows for apps in backup
        for app_meta in apps:
            row = Adw.ActionRow(title=app_meta.get("name", _("Unknown")))
            sub_parts = []
            if app_meta.get("has_binary"):
                size = app_meta.get("binary_size", 0)
                sub_parts.append(gnu_naturalsize(size))
            else:
                sub_parts.append(_("Configuration only (binary not included)"))

            if app_meta.get("app_data"):
                sub_parts.append(_("{n} data folders").format(n=len(app_meta["app_data"])))

            row.set_subtitle(" · ".join(sub_parts))

            check = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
            check.connect('toggled', lambda _: self.update_restore_selection_count())
            row.add_prefix(check)

            icon_img = Gtk.Image.new_from_icon_name("application-x-executable")
            icon_img.set_pixel_size(32)
            row.add_prefix(icon_img)

            self.restore_apps_group.add(row)
            self.restore_app_rows.append({"meta": app_meta, "check": check, "row": row})

        self.restore_options_group.set_visible(True)
        self.restore_apps_group.set_visible(True)
        self.restore_action_group.set_visible(True)

        self.update_restore_selection_count()

    def update_restore_selection_count(self):
        selected_count = sum(1 for item in self.restore_app_rows if item["check"].get_active())
        total = len(self.restore_app_rows)
        self.restore_selection_count_label.set_label(f"{selected_count} / {total} " + _("selected"))
        self.perform_restore_btn.set_sensitive(selected_count > 0)

    def set_all_restore_selection(self, select: bool):
        for item in self.restore_app_rows:
            item["check"].set_active(select)
        self.update_restore_selection_count()

    def on_choose_restore_folder_clicked(self, widget):
        dialog = Gtk.FileDialog(title=_("Select Destination Folder"), modal=True)
        dialog.select_folder(
            parent=self,
            cancellable=None,
            callback=self.on_select_restore_folder_response
        )

    def on_select_restore_folder_response(self, dialog, result):
        try:
            selected_folder = dialog.select_folder_finish(result)
            self.restore_dest_folder = selected_folder.get_path()
            self.restore_dest_row.set_subtitle(self.restore_dest_folder)
        except Exception as e:
            logging.info(f"Folder select cancelled: {e}")

    def on_perform_restore_clicked(self, widget):
        selected_names = [item["meta"]["name"] for item in self.restore_app_rows if item["check"].get_active()]
        if not selected_names or not self.loaded_backup_path:
            return

        self.perform_restore_btn.set_sensitive(False)
        self.restore_progress_bar.set_visible(True)
        self.restore_status_label.set_visible(True)
        self.restore_progress_bar.set_fraction(0.0)

        restore_data = self.restore_app_data_switch.get_active()
        self._run_restore_async(self.loaded_backup_path, selected_names, self.restore_dest_folder, restore_data)

    @_async
    def _run_restore_async(self, archive_path, names, dest_folder, restore_data):
        def on_progress(cur, total, status_text):
            fraction = cur / max(total, 1)
            self._update_restore_progress(fraction, status_text)

        try:
            results = BackupManager.restore_backup(
                archive_path=archive_path,
                selected_app_names=names,
                destination_folder=dest_folder,
                restore_app_data=restore_data,
                progress_callback=on_progress
            )
            self._on_restore_finished(True, len(results), "")
        except Exception as e:
            logging.error(f"Restore failed: {e}")
            self._on_restore_finished(False, 0, str(e))

    @idle
    def _update_restore_progress(self, fraction, text):
        self.restore_progress_bar.set_fraction(fraction)
        self.restore_status_label.set_label(text)

    @idle
    def _on_restore_finished(self, success, count, error_message):
        self.perform_restore_btn.set_sensitive(True)
        self.restore_progress_bar.set_visible(False)
        self.restore_status_label.set_visible(False)

        if success:
            toast = Adw.Toast.new(_("Restored successfully!"))
            self.toast_overlay.add_toast(toast)

            msg = _("Successfully restored {count} applications to:\n{dest}").format(
                count=count, dest=self.restore_dest_folder
            )
            show_message_dialog(msg, header=_("Restore Complete"))

            # Refresh parent window list if available
            if self.parent_window and hasattr(self.parent_window, "installed_apps_list"):
                self.parent_window.installed_apps_list.refresh_list()
        else:
            show_message_dialog(
                _("An error occurred during restoration:\n") + error_message,
                header=_("Restore Failed")
            )
