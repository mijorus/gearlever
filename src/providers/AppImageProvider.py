import logging
import re
import os
import shutil
import hashlib
import dbus
import filecmp
from xdg import DesktopEntry
import subprocess
import signal

from ..lib import terminal
from ..models.AppListElement import AppListElement, InstalledStatus
from ..lib.async_utils import _async
from ..lib.utils import log, cleanhtml, get_giofile_content_type, get_gsettings, create_dict, gio_copy, get_file_hash
from ..components.CustomComponents import LabelStart
from ..models.Models import FlatpakHistoryElement, AppUpdateElement, InternalError
from typing import List, Callable, Union, Dict, Optional, List, TypedDict
from gi.repository import GLib, Gtk, Gdk, GdkPixbuf, Gio, GObject, Pango, Adw
from enum import Enum


class ExtractedAppImage():
    desktop_entry: Optional[DesktopEntry.DesktopEntry]
    extraction_folder: Optional[Gio.File]
    appimage_file: Gio.File
    desktop_file: Optional[Gio.File]
    icon_file: Optional[Gio.File]
    md5: str

class AppImageUpdateLogic(Enum):
    REPLACE = 'REPLACE'
    KEEP = 'KEEP'

class AppImageListElement(AppListElement):
    def __init__(self, file_path: str, desktop_entry: Optional[DesktopEntry.DesktopEntry], icon: Optional[str], **kwargs):
        super().__init__(**kwargs)
        self.file_path = file_path
        self.desktop_entry = desktop_entry
        self.icon = icon
        self.extracted: Optional[ExtractedAppImage] = None
        self.trusted = (self.installed_status is InstalledStatus.INSTALLED)
        self.update_logic: Optional[AppImageUpdateLogic] = None
        self.local_file = kwargs['local_file'] if 'local_file' in kwargs else False


class AppImageProvider():
    def __init__(self):
        self.name = 'appimage'
        self.icon = "/it/mijorus/gearlever/assets/App-image-logo.png"
        logging.info(f'Activating {self.name} provider')

        self.supported_mimes = ['application/vnd.appimage', 'application/x-iso9660-appimage']

        self.general_messages = []
        self.update_messages = []

        self.modal_gfile: Optional[Gio.File] = None
        self.modal_gfile_createshortcut_check: Optional[Gtk.CheckButton] = None
        self.extraction_folder = GLib.get_tmp_dir() + '/it.mijorus.gearlever/appimages'
        self.mount_appimage_process: Optional[subprocess.Popen]

    def list_installed(self) -> List[AppImageListElement]:
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
                        version = entry.get('X-AppImage-Version')

                        if entry.getExec().startswith(default_folder_path) and GLib.file_test(entry.getExec(), GLib.FileTest.EXISTS):
                            list_element = AppImageListElement(
                                name=entry.getName(),
                                description=entry.getComment(),
                                icon=entry.getIcon(),
                                app_id='',
                                version=f"v. {entry.get('X-AppImage-Version')}",
                                installed_status=InstalledStatus.INSTALLED,
                                file_path=entry.getExec(),
                                provider=self.name,
                                desktop_entry=entry,
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

                if get_giofile_content_type(installed_gfile) in self.supported_mimes:
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

            if el.trusted:
                extracted = self.extract_appimage(el)

                if extracted.icon_file and os.path.exists(extracted.icon_file.get_path()):
                    return Gtk.Image.new_from_file(extracted.icon_file.get_path())

        return Gtk.Image(icon_name='application-x-executable-symbolic')

    def get_description(self, el: AppImageListElement) -> str:
        if el.desktop_entry:
            return el.desktop_entry.getComment()
        
        return ''

    def refresh_title(self, el: AppImageListElement) -> str:
        if el.desktop_entry:
            el.name = el.desktop_entry.getName()
        
        if el.trusted:
            extracted = self.extract_appimage(el)
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
        return get_giofile_content_type(file) in self.supported_mimes

    def is_updatable(self, el: AppImageListElement) -> bool:
        for item in self.list_installed():
            if item.name == el.name:
                return True
        
        return False

    def install_file(self, el: AppImageListElement):
        logging.info('Installing appimage: ' + el.file_path)
        el.installed_status = InstalledStatus.INSTALLING
        extracted_appimage: Optional[ExtractedAppImage] = None

        try:
            extracted_appimage = self.extract_appimage(el)
            dest_file_info = extracted_appimage.appimage_file.query_info('*', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)

            # Move .appimage to its default location
            appimages_destination_path = self.get_appimages_default_destination_path()

            if not os.path.exists(f'{appimages_destination_path}'):
                os.mkdir(f'{appimages_destination_path}')

            # how the appimage will be called
            safe_app_name = f'gearlever_{dest_file_info.get_name()}'
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

                with open(extracted_appimage.desktop_file.get_path(), 'r') as dskt_file:
                    desktop_file_content = dskt_file.read()

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

                        version = extracted_appimage.desktop_entry.get('X-AppImage-Version') 
                        
                        if not version:
                            version = extracted_appimage.md5[0:6]
                            desktop_file_content += f'\nX-AppImage-Version={version}'

                        if el.update_logic is AppImageUpdateLogic.KEEP:
                            final_app_name += f' ({version})'

                    final_app_name = final_app_name.strip()
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

        except Exception as e:
            logging.error('Appimage installation error: ' + str(e))

        try:
            self.post_file_extraction_cleanup(extracted_appimage)
        except Exception as g:
            logging.error('Appimage cleanup error: ' + str(g))

        terminal.sh(['update-desktop-database', '-q'])

    def create_list_element_from_file(self, file: Gio.File) -> AppImageListElement:
        app_name: str = file.get_parse_name().split('/')[-1]

        el = AppImageListElement(
            name=re.sub('\.appimage$', '', app_name, 1, re.IGNORECASE),
            description='',
            app_id='MD5: ' + get_file_hash(file),
            provider=self.name,
            installed_status=InstalledStatus.NOT_INSTALLED,
            file_path=file.get_path(),
            desktop_entry=None,
            icon=None,
            local_file=True
        )

        if self.is_installed(el):
            for installed in self.list_installed():
                if filecmp.cmp(installed.file_path, el.file_path, shallow=False):
                    return installed

        return el

    def post_file_extraction_cleanup(self, extraction: ExtractedAppImage):
        if Gio.File.new_for_path(f'{self.extraction_folder}'):
            logging.debug(f'Clearing {self.extraction_folder}')
            shutil.rmtree(self.extraction_folder)

    def mount_appimage(self, file_path: str) -> str:
        # Start the process and redirect its standard output to a pipe
        self.process = subprocess.Popen(['flatpak-spawn', '--host', file_path, '--appimage-mount'], stdout=subprocess.PIPE)

        if self.process.stdout:
            # Read the output of the process line by line
            while True:
                output = self.process.stdout.readline()
                if output == '' and self.process.poll() is not None:
                    break
                if output:
                    out = output.decode('utf-8').strip()
                    logging.debug(f'Appimage, mounted {out}')

                    return out
        
        raise InternalError('Failed to mount appimage')
    
    def unmount_appimage(self):
        if self.process:
            logging.debug(f'Appimage, unmounted')
            self.process.send_signal(signal.SIGTERM)

    def extract_appimage(self, el: AppImageListElement) -> ExtractedAppImage:
        if not el.trusted:
            raise InternalError(message=_('Cannot load an untrusted AppImage'))
        
        if el.extracted:
            return el.extracted

        file = Gio.File.new_for_path(el.file_path)

        if get_giofile_content_type(file) in ['application/x-iso9660-appimage']:
            raise Exception('This file format cannot be extracted!')

        icon_file: Optional[Gio.File] = None
        desktop_file: Optional[Gio.File] = None

        desktop_entry: Optional[DesktopEntry.DesktopEntry] = None
        extraction_folder = None

        # hash file
        md5_hash = get_file_hash(file)
        temp_file_name = 'gearlever_appimage_' + md5_hash
        tmp_folder = Gio.File.new_for_path(f'{GLib.get_tmp_dir()}/{temp_file_name}')

        if tmp_folder.query_exists():
            shutil.rmtree(tmp_folder.get_path())

        if tmp_folder.make_directory_with_parents(None):
            tmp_file = Gio.File.new_for_path(f'{tmp_folder.get_path()}/{temp_file_name}')
            file_copy_success = file.copy(tmp_file, Gio.FileCopyFlags.OVERWRITE, None, None, None, None)

            if file_copy_success:
                os.chmod(tmp_file.get_path(), 0o755)
                
                mounted_appimage_path = self.mount_appimage(tmp_file.get_path())
                extraction_folder = Gio.File.new_for_path(mounted_appimage_path)

                try:
                    if not extraction_folder.query_exists():
                        raise InternalError('Missing mounted extraction folder')

                    desktop_file = None
                    for d in  os.listdir(f'{extraction_folder.get_path()}'):
                        if not d.endswith('.desktop'):
                            continue

                        gdesk_file = Gio.File.new_for_path(f'{extraction_folder.get_path()}/{d}')
                        if get_giofile_content_type(gdesk_file) == 'application/x-desktop':
                            desktop_file = gdesk_file
                            # gdesk_file.copy(desktop_file, Gio.FileCopyFlags.OVERWRITE, None, None, None, None)

                            break

                    desktop_entry_icon = None
                    if desktop_file:
                        desktop_entry = DesktopEntry.DesktopEntry(desktop_file.get_path())
                        desktop_entry_icon = desktop_entry.getIcon()

                    if desktop_entry_icon:
                        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#the-filesystem-image

                        for icon_xt in ['.svg', '.png']:
                            icon_xt_f = Gio.File.new_for_path(extraction_folder.get_path() + f'/{desktop_entry_icon}{icon_xt}')

                            if icon_xt_f.query_exists():
                                icon_file = icon_xt_f
                                break

                        if icon_xt_f.get_path().endswith('.png'):
                            # always prefer svg(s) to png(s)
                            # if a png is not found in the root of the filesystem, try somewhere else

                            try_paths = [
                                extraction_folder.get_path() + f'/usr/share/icons/hicolor/scalable/apps/{desktop_entry_icon}.svg',
                                extraction_folder.get_path() + f'/usr/share/icons/hicolor/256x256/apps/{desktop_entry_icon}.png',
                                extraction_folder.get_path() + f'/usr/share/icons/hicolor/128x128/apps/{desktop_entry_icon}.png'
                            ]

                            for icon_xt in try_paths:
                                icon_xt_f = Gio.File.new_for_path(icon_xt)

                                if icon_xt_f.query_exists():
                                    icon_file = icon_xt_f
                                    break

                except Exception as e:
                    logging.error(str(e))

                finally:
                    self.unmount_appimage()

        result = ExtractedAppImage()
        result.desktop_entry = desktop_entry
        result.extraction_folder = extraction_folder
        result.appimage_file = tmp_file
        result.desktop_file = desktop_file
        result.icon_file = icon_file
        result.md5 = md5_hash

        el.desktop_entry = desktop_entry
        el.extracted = result


        return result

    def get_appimages_default_destination_path(self) -> str:
        return get_gsettings().get_string('appimages-default-folder').replace('~', GLib.get_home_dir())