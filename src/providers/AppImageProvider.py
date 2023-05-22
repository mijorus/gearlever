import logging
import re
import os
import shutil
import hashlib
import dbus
import filecmp
from xdg import DesktopEntry

from ..lib import terminal
from ..models.AppListElement import AppListElement, InstalledStatus
from ..lib.async_utils import _async
from ..lib.utils import log, cleanhtml, key_in_dict, gtk_image_from_url, qq, get_application_window, get_giofile_content_type, get_gsettings, create_dict, gio_copy, get_file_hash
from ..components.CustomComponents import LabelStart
from ..models.Provider import Provider
from ..models.Models import FlatpakHistoryElement, AppUpdateElement
from typing import List, Callable, Union, Dict, Optional, List, TypedDict
from gi.repository import GLib, Gtk, Gdk, GdkPixbuf, Gio, GObject, Pango, Adw


class ExtractedAppImage():
    desktop_entry: Optional[DesktopEntry.DesktopEntry]
    extraction_folder: Optional[Gio.File]
    container_folder: Gio.File
    appimage_file: Gio.File
    desktop_file: Optional[Gio.File]
    icon_file: Optional[Gio.File]


class AppImageListElement(AppListElement):
    def __init__(self, file_path: str, desktop_entry: Optional[DesktopEntry.DesktopEntry], icon: Optional[str], **kwargs):
        super().__init__(**kwargs)
        self.file_path = file_path
        self.desktop_entry = desktop_entry
        self.icon = icon


class AppImageProvider():
    def __init__(self):
        self.name = 'appimage'
        self.icon = "/it/mijorus/boutique/assets/App-image-logo.png"
        self.small_icon = "/it/mijorus/boutique/assets/appimage-showcase.png"
        logging.info(f'Activating {self.name} provider')

        self.general_messages = []
        self.update_messages = []

        self.modal_gfile: Optional[Gio.File] = None
        self.modal_gfile_createshortcut_check: Optional[Gtk.CheckButton] = None

    def list_installed(self) -> List[AppListElement]:
        default_folder_path = self.get_appimages_default_destination_path()
        output = []

        try:
            folder = Gio.File.new_for_path(default_folder_path)
            desktop_files_dir = f'{GLib.get_user_data_dir()}/applications/'

            for file_name in os.listdir(desktop_files_dir):
                gfile = Gio.File.new_for_path(desktop_files_dir + f'/{file_name}')

                try:
                    if get_giofile_content_type(gfile) == 'application/x-desktop':

                        entry = DesktopEntry.DesktopEntry(filename=gfile.get_path())
                        if entry.getExec().startswith(default_folder_path) and GLib.file_test(entry.getExec(), GLib.FileTest.EXISTS):
                            list_element = AppImageListElement(
                                name=entry.getName(),
                                description=entry.getComment(),
                                icon=entry.getIcon(),
                                app_id='',
                                version=entry.get('X-AppImage-Version'),
                                installed_status=InstalledStatus.INSTALLED,
                                file_path=entry.getExec(),
                                provider=self.name,
                                desktop_entry=entry
                            )

                            output.append(list_element)

                except Exception as e:
                    logging.warn(e)

        except Exception as e:
            logging.error(e)

        return output

    def is_installed(self, el: AppImageListElement) -> bool:
        if el.file_path and os.path.exists(self.get_appimages_default_destination_path()):
            for file_name in os.listdir(self.get_appimages_default_destination_path()):
                installed_gfile = Gio.File.new_for_path(self.get_appimages_default_destination_path() + '/' + file_name)
                loaded_gfile = Gio.File.new_for_path(el.file_path)

                if get_giofile_content_type(installed_gfile) == 'application/vnd.appimage':
                    if filecmp.cmp(installed_gfile.get_path(), loaded_gfile.get_path(), shallow=False):
                        el.file_path = installed_gfile.get_path()
                        return True

        return False

    def get_icon(self, el: AppImageListElement) -> Gtk.Image:
        icon_path = None

        if el.desktop_entry:
            icon_path = el.desktop_entry.getIcon()

        if icon_path and os.path.exists(icon_path):
            return Gtk.Image.new_from_file(icon_path)
        else:
            icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())

            if el.desktop_entry and icon_theme.has_icon(el.desktop_entry.getIcon()):
                return Gtk.Image.new_from_icon_name(el.desktop_entry.getIcon())

            extracted = self.extract_appimage(el.file_path, el)

            if extracted.icon_file and os.path.exists(extracted.icon_file.get_path()):
                return Gtk.Image.new_from_file(extracted.icon_file.get_path())

        return Gtk.Image(icon_name='application-x-executable-symbolic')

    def refresh_title(self, el: AppImageListElement) -> str:
        if el.desktop_entry:
            el.name = el.desktop_entry.getName()
        
        extracted = self.extract_appimage(el.file_path, el)
        if extracted.desktop_entry:
            el.name = extracted.desktop_entry.getName()
        
        return el.name

    def uninstall(self, el: AppImageListElement):
        os.remove(el.file_path)

        if el.desktop_entry:
            os.remove(el.desktop_entry.getFileName())

        el.set_installed_status(InstalledStatus.NOT_INSTALLED)

    def install(self, el: AppListElement):
        print('qwe')

    def search(self, query: str) -> List[AppListElement]:
        return []

    def get_long_description(self, el: AppListElement) -> str:
        return ''

    def load_extra_data_in_appdetails(self, widget: Gtk.Widget, list_element: AppListElement):
        pass

    def list_updatables(self) -> List[AppUpdateElement]:
        return []

    def update(self, el: AppListElement):
        pass

    def update_all(self, callback: Callable[[bool, str, bool], None]):
        pass

    def updates_need_refresh(self) -> bool:
        return False

    def run(self, el: AppImageListElement):
        os.chmod(el.file_path, 0o755)
        # if not os.access(el.file_path, os.X_OK):

        terminal.threaded_sh([f'{el.file_path}'])
            
    def can_install_file(self, file: Gio.File) -> bool:
        return get_giofile_content_type(file) in ['application/vnd.appimage', 'application/x-iso9660-appimage']

    def is_updatable(self, app_id: str) -> bool:
        return False

    def install_file(self, el: AppImageListElement):
        logging.info('Installing appimage: ' + el.file_path)
        el.installed_status = InstalledStatus.INSTALLING
        extracted_appimage: Optional[ExtractedAppImage] = None

        try:
            extracted_appimage = self.extract_appimage(file_path=el.file_path)
            dest_file_info = extracted_appimage.appimage_file.query_info('*', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)

            if extracted_appimage.extraction_folder.query_exists():
                # Move .appimage to its default location
                appimages_destination_path = self.get_appimages_default_destination_path()

                # how the appimage will be called
                safe_app_name = f'boutique_{dest_file_info.get_name()}'
                if extracted_appimage.desktop_entry:
                    safe_app_name = f'{terminal.sanitize(extracted_appimage.desktop_entry.getName())}_{dest_file_info.get_name()}'

                dest_appimage_file = Gio.File.new_for_path(appimages_destination_path + '/' + safe_app_name + '.appimage')

                if gio_copy(extracted_appimage.appimage_file, dest_appimage_file):
                    log(f'file copied to {appimages_destination_path}')

                    os.chmod(dest_appimage_file.get_path(), 0o755)
                    el.file_path = dest_appimage_file.get_path()

                    # copy the icon file
                    icon_file = None
                    dest_appimage_icon_file = None
                    if extracted_appimage.desktop_entry:
                        icon_file = extracted_appimage.icon_file

                    if icon_file and os.path.exists(icon_file.get_path()):
                        if not os.path.exists(f'{appimages_destination_path}/.icons'):
                            os.mkdir(f'{appimages_destination_path}/.icons')

                        dest_appimage_icon_file = Gio.File.new_for_path(f'{appimages_destination_path}/.icons/{safe_app_name}')
                        gio_copy(icon_file, dest_appimage_icon_file)

                    # Move .desktop file to its default location
                    dest_destop_file_path = f'{GLib.get_user_data_dir()}/applications/{safe_app_name}.desktop'
                    dest_destop_file_path = dest_destop_file_path.replace(' ', '_')

                    with open(extracted_appimage.desktop_file.get_path(), 'r') as desktop_file_python:
                        desktop_file_content = desktop_file_python.read()

                        # replace executable path
                        desktop_file_content = re.sub(
                            r'Exec=.*$',
                            f"Exec={dest_appimage_file.get_path()}",
                            desktop_file_content,
                            flags=re.MULTILINE
                        )

                        # replace icon path
                        desktop_file_content = re.sub(
                            r'Icon=.*$',
                            f"Icon={dest_appimage_icon_file.get_path() if dest_appimage_icon_file else 'applications-other'}",
                            desktop_file_content,
                            flags=re.MULTILINE
                        )

                        # generate a new app name
                        final_app_name = extracted_appimage.appimage_file.get_basename()
                        if extracted_appimage.desktop_entry:
                            final_app_name = f"{extracted_appimage.desktop_entry.getName()}"
                            # if extracted_appimage.desktop_entry.get('X-AppImage-Version'):
                            #     final_app_name += f' ({extracted_appimage.desktop_entry.get("X-AppImage-Version")})'

                        desktop_file_content = re.sub(
                            r'Name=.*$',
                            f"Name={final_app_name}",
                            desktop_file_content,
                            flags=re.MULTILINE
                        )

                        # finally, write the new .desktop file
                        with open(dest_destop_file_path, 'w+') as desktop_file_python_dest:
                            desktop_file_python_dest.write(desktop_file_content)

                    if os.path.exists(dest_destop_file_path):
                        el.desktop_entry = DesktopEntry.DesktopEntry(filename=dest_destop_file_path)
                        el.installed_status = InstalledStatus.INSTALLED
            else:
                logging.info('errore')
                raise Exception('Extraction folder does not exists')

        except Exception as e:
            logging.error('Appimage installation error: ' + str(e))

        try:
            self.post_file_extraction_cleanup(extracted_appimage)
        except Exception as g:
            pass

        terminal.sh(['update-desktop-database'])

    def create_list_element_from_file(self, file: Gio.File) -> AppImageListElement:
        app_name: str = file.get_parse_name().split('/')[-1]

        return AppImageListElement(
            name=re.sub('\.appimage$', '', app_name, 1, re.IGNORECASE),
            description='',
            app_id='MD5: ' + hashlib.md5(open(file.get_path(), 'rb').read()).hexdigest(),
            provider=self.name,
            installed_status=InstalledStatus.NOT_INSTALLED,
            file_path=file.get_path(),
            desktop_entry=None,
            icon=None
        )

    # def open_file_dialog(self, file: Gio.File, parent: Gtk.Widget):
    #     self.modal_gfile = file
    #     app_name: str = file.get_parse_name().split('/')[-1]
    #     modal_text = f"<b>You are trying to open the following AppImage: </b>\n\n📦️ {app_name}"
    #     modal_text += '\n\nAppImages are self-contained applications that\ncan be executed without requiring installation'
    #     modal_text += '\n\nYou can decide to execute this app immediately\nor create a desktop shortcut for faster access.\n'

    #     extra_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    #     modal_text_label = Gtk.Label()
    #     modal_text_label.set_markup(modal_text)
    #     extra_content.append(modal_text_label)

    #     self.modal_gfile_createshortcut_check = Gtk.CheckButton(label='Create a desktop shortcut')
    #     extra_content.append(self.modal_gfile_createshortcut_check)

    #     self.open_file_options_dialog = Adw.MessageDialog(
    #         heading='Opening sideloaded AppImage',
    #         body='',
    #         extra_child=extra_content
    #     )

    #     self.open_file_options_dialog.add_response('cancel', 'Cancel')
    #     self.open_file_options_dialog.add_response('run', 'Run')
    #     self.open_file_options_dialog.set_response_appearance('cancel', Adw.ResponseAppearance.DESTRUCTIVE)
    #     self.open_file_options_dialog.set_response_appearance('run', Adw.ResponseAppearance.SUGGESTED)

    #     self.open_file_options_dialog.connect('response', self.on_file_dialog_run_option_selected)
    #     self.open_file_options_dialog.set_transient_for(parent)
    #     return self.open_file_options_dialog

    # def on_file_dialog_run_option_selected(self, widget: Adw.MessageDialog, user_response: str):
    #     if user_response == 'run' and self.modal_gfile:
    #         logging.info('Running appimage: ' + self.modal_gfile.get_path())
    #         os.chmod(self.modal_gfile.get_path(), 0o755)
    #         terminal.threaded_sh([self.modal_gfile.get_path()])

    #         if self.modal_gfile_createshortcut_check and (self.modal_gfile_createshortcut_check.get_active()):
    #             l = AppListElement(
    #                 name=self.modal_gfile.get_path(), 
    #                 description='', 
    #                 app_id=get_file_hash(self.modal_gfile), 
    #                 provider=self.name,
    #                 installed_status=InstalledStatus.NOT_INSTALLED, 
    #                 file_path=self.modal_gfile.get_path()
    #             )

    #             self.install_file(l, lambda x: None)

    #     self.modal_gfile_createshortcut_check = None
    #     self.modal_gfile = None
    #     self.open_file_options_dialog.close()

    def post_file_extraction_cleanup(self, extraction: ExtractedAppImage):
        print(extraction.container_folder.get_path())
        if extraction.container_folder.query_exists():
            shutil.rmtree(extraction.container_folder.get_path())

    def extract_appimage(self, file_path: str, el: Optional[AppImageListElement]=None) -> ExtractedAppImage:

        file = Gio.File.new_for_path(file_path)

        if get_giofile_content_type(file) in ['application/x-iso9660-appimage']:
            raise Exception('This file format cannot be extracted!')

        icon_file: Optional[Gio.File] = None
        desktop_file: Optional[Gio.File] = None

        desktop_entry: Optional[DesktopEntry.DesktopEntry] = None
        extraction_folder = None

        temp_file = None

        # hash file
        temp_file = 'boutique_appimage_' + get_file_hash(file)
        folder = Gio.File.new_for_path(GLib.get_tmp_dir() + f'/it.mijorus.boutique/appimages/{temp_file}')

        if folder.query_exists():
            shutil.rmtree(folder.get_path())

        if folder.make_directory_with_parents(None):
            dest_file = Gio.File.new_for_path(folder.get_path() + f'/{temp_file}')
            file_copy = file.copy(
                dest_file,
                Gio.FileCopyFlags.OVERWRITE,
                None, None, None, None
            )

            dest_file_info = dest_file.query_info('*', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)

            if file_copy:
                squash_folder = Gio.File.new_for_path(f'{folder.get_path()}/squashfs-root')

                # set exec permission for dest_file
                os.chmod(dest_file.get_path(), 0o755)
                logging.info('Appimage, extracting ' + file_path)
                terminal.sh(["bash", "-c", f"cd {folder.get_path()} && {dest_file.get_path()} --appimage-extract"])

                if squash_folder.query_exists():
                    extraction_folder = squash_folder

                    desktop_files: list[str] = filter(lambda x: x.endswith('.desktop'), os.listdir(f'{folder.get_path()}/squashfs-root'))

                    for d in desktop_files:
                        gdesk_file = Gio.File.new_for_path(f'{folder.get_path()}/squashfs-root/{d}')
                        if get_giofile_content_type(gdesk_file) == 'application/x-desktop':
                            desktop_file = gdesk_file
                            break

                    if desktop_file:
                        desktop_entry = DesktopEntry.DesktopEntry(desktop_file.get_path())

                        if desktop_entry.getIcon():
                            # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#the-filesystem-image
                            for icon_xt in ['.png', '.svgz', '.svg']:
                                icon_xt_f = Gio.File.new_for_path(extraction_folder.get_path() + f'/{desktop_entry.getIcon()}{icon_xt}')

                                if icon_xt_f.query_exists():
                                    icon_file = icon_xt_f
                                    break

        result = ExtractedAppImage()
        result.desktop_entry = desktop_entry
        result.extraction_folder = extraction_folder
        result.container_folder = folder
        result.appimage_file = dest_file
        result.desktop_file = desktop_file
        result.icon_file = icon_file

        if el:
            el.desktop_entry = desktop_entry

        return result

    def get_appimages_default_destination_path(self) -> str:
        return get_gsettings().get_string('appimages-default-folder').replace('~', GLib.get_home_dir())

    def get_previews(self, el):
        return []

    def get_available_from_labels(self, el):
        return el.file_path

    def get_installed_from_source(self, el):
        return 'Local file'
