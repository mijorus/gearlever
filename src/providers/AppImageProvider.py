import logging
import re
import os
import shutil
import filecmp
from xdg import DesktopEntry
import subprocess
import random
import signal

from ..lib import terminal
from ..models.AppListElement import AppListElement, InstalledStatus
from ..lib.async_utils import _async
from ..lib.utils import log, get_giofile_content_type, get_gsettings, gio_copy, get_file_hash
from ..models.Models import FlatpakHistoryElement, AppUpdateElement, InternalError
from typing import List, Callable, Union, Dict, Optional, List, TypedDict
from gi.repository import GLib, Gtk, Gdk, GdkPixbuf, Gio, GObject, Pango, Adw
from enum import Enum
from dataclasses import dataclass


class ExtractedAppImage():
    extraction_folder: str
    desktop_entry: Optional[DesktopEntry.DesktopEntry]
    appimage_file: Gio.File
    desktop_file: Optional[Gio.File]
    icon_file: Optional[Gio.File]
    md5: str

class AppImageUpdateLogic(Enum):
    REPLACE = 'REPLACE'
    KEEP = 'KEEP'

@dataclass
class AppImageListElement():
    name: str 
    description: str
    provider: str
    installed_status: InstalledStatus
    file_path: str
    generation: int
    trusted: bool = False
    desktop_entry: Optional[DesktopEntry.DesktopEntry] = None
    update_logic: Optional[AppImageUpdateLogic] = None
    version: Optional[str] = None
    extracted: Optional[ExtractedAppImage] = None
    local_file: Optional[Gio.File] = None
    size: Optional[float] = None
    external_folder: bool = False

    def set_installed_status(self, installed_status: InstalledStatus):
        self.installed_status = installed_status
        
    def set_trusted(self):
        os.chmod(self.file_path, 0o755)
        self.trusted = True


class AppImageProvider():
    def __init__(self):
        self.name = 'AppImage'
        self.icon = "/it/mijorus/gearlever/assets/App-image-logo.png"
        logging.info(f'Activating {self.name} provider')

        self.supported_mimes = ['application/x-iso9660-appimage', 'application/vnd.appimage']

        self.general_messages = []
        self.update_messages = []

        self.extraction_folder = GLib.get_tmp_dir() + '/it.mijorus.gearlever/appimages'
        self.user_desktop_files_path = f'{GLib.get_home_dir()}/.local/share/applications/'

    def list_installed(self) -> List[AppImageListElement]:
        default_folder_path = self._get_appimages_default_destination_path()
        manage_from_outside = get_gsettings().get_boolean('manage-files-outside-default-folder')
        output = []

        if not os.path.exists(self.user_desktop_files_path):
            return output

        for file_name in os.listdir(self.user_desktop_files_path):
            gfile = Gio.File.new_for_path(self.user_desktop_files_path + f'/{file_name}')

            try:
                if os.path.isfile(gfile.get_path()) and get_giofile_content_type(gfile) == 'application/x-desktop':
                    entry = DesktopEntry.DesktopEntry(filename=gfile.get_path())

                    if os.path.isfile(entry.getExec()):
                        exec_gfile = Gio.File.new_for_path(entry.getExec())
                        exec_in_defalut_folder = os.path.isfile(f'{default_folder_path}/{exec_gfile.get_basename()}')
                        exec_in_folder = True if manage_from_outside else exec_in_defalut_folder

                        if exec_in_folder and self.can_install_file(exec_gfile):
                            list_element = AppImageListElement(
                                name=entry.getName(),
                                description=entry.getComment(),
                                version=entry.get('X-AppImage-Version'),
                                installed_status=InstalledStatus.INSTALLED,
                                file_path=entry.getExec(),
                                provider=self.name,
                                desktop_entry=entry,
                                trusted=True,
                                generation=self.get_appimage_generation(exec_gfile),
                                external_folder=(not exec_in_defalut_folder)
                            )

                            output.append(list_element)

            except Exception as e:
                logging.warn(e)

        return output

    def is_installed(self, el: AppImageListElement) -> bool:
        if el.file_path and os.path.exists(self._get_appimages_default_destination_path()):
            for file_name in os.listdir(self._get_appimages_default_destination_path()):
                installed_gfile = Gio.File.new_for_path(self._get_appimages_default_destination_path() + '/' + file_name)
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

        if icon_path and os.path.isfile(icon_path):
            return Gtk.Image.new_from_file(icon_path)
        else:
            icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())

            if el.desktop_entry and icon_theme.has_icon(el.desktop_entry.getIcon()):
                return Gtk.Image.new_from_icon_name(el.desktop_entry.getIcon())

            if el.trusted:
                extracted = self._load_appimage_metadata(el)

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
            extracted = self._load_appimage_metadata(el)
            if extracted.desktop_entry:
                el.name = extracted.desktop_entry.getName()
        
        return el.name

    def uninstall(self, el: AppImageListElement):
        logging.info(f'Removing {el.file_path}')
        os.remove(el.file_path)

        if el.desktop_entry:
            logging.info(f'Removing {el.desktop_entry.getFileName()}')
            os.remove(el.desktop_entry.getFileName())

        el.set_installed_status(InstalledStatus.NOT_INSTALLED)

    def install(self, el: AppListElement):
        pass

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
        if el.trusted:
            terminal.host_threaded_sh([f'{el.file_path}'], return_stderr=True)

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
            extracted_appimage = self._load_appimage_metadata(el)
            dest_file_info = extracted_appimage.appimage_file.query_info('*', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)

            # Move .appimage to its default location
            appimages_destination_path = self._get_appimages_default_destination_path()

            if not os.path.exists(f'{appimages_destination_path}'):
                os.mkdir(f'{appimages_destination_path}')

            # how the appimage will be called
            safe_app_name = f'gearlever_{dest_file_info.get_name()}'
            if extracted_appimage.desktop_entry:
                safe_app_name = 'gearlever_' + extracted_appimage.desktop_entry.getName()
            
            safe_app_name = re.sub(r"[^A-Za-z0-9_]+", "", safe_app_name).lower() + '_' + extracted_appimage.md5[0:6] + '.appimage'
            
            append_file_ext = True
            if extracted_appimage.desktop_entry and get_gsettings().get_boolean('exec-as-name-for-terminal-apps') and extracted_appimage.desktop_entry.getTerminal():
                safe_app_name = extracted_appimage.desktop_entry.getExec()
                append_file_ext = False

            # if there is already an app with the same name, 
            # we try not to overwrite

            i = 1
            while safe_app_name in os.listdir(self._get_appimages_default_destination_path()):
                safe_app_name =  re.sub(r'(_\d+)?\.appimage', '', safe_app_name) + f'_{i}' + ('.appimage' if append_file_ext else '')
                i += 1

            dest_appimage_file = Gio.File.new_for_path(appimages_destination_path + '/' + safe_app_name)

            if not gio_copy(extracted_appimage.appimage_file, dest_appimage_file):
                raise InternalError('Error while moving appimage file to the destination folder')

            log(f'file copied to {appimages_destination_path}')

            self._make_file_executable(el, dest_appimage_file.get_path())
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
            dest_destop_file_path = f'{self.user_desktop_files_path}/{safe_app_name}.desktop'
            dest_destop_file_path = dest_destop_file_path.replace(' ', '_')

            with open(extracted_appimage.desktop_file.get_path(), 'r') as dskt_file:
                desktop_file_content = dskt_file.read()

                # replace executable path
                desktop_file_content = re.sub(
                    r'^Exec=.*$',
                    f"Exec={dest_appimage_file.get_path()}",
                    desktop_file_content,
                    flags=re.MULTILINE
                )

                # replace icon path
                desktop_file_content = re.sub(
                    r'^Icon=.*$',
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

                        desktop_file_content = re.sub(
                            r'^Name\[(.*?)\]=.*$',
                            '',
                            desktop_file_content,
                            flags=re.MULTILINE
                        )

                final_app_name = final_app_name.strip()
                desktop_file_content = re.sub(
                    r'^Name=.*$',
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
            raise e

        if get_gsettings().get_boolean('move-appimage-on-integration'):
            logging.info('Deleting original appimage file from: '  + extracted_appimage.appimage_file.get_path())
            if not extracted_appimage.appimage_file.delete(None):
                raise InternalError('Cannot delete original file')

        try:
            self.extraction_folder_cleanup()
        except Exception as g:
            logging.error('Appimage cleanup error: ' + str(g))
            raise g


        update_dkt_db = terminal.host_sh(['update-desktop-database', self.user_desktop_files_path, '-v'], return_stderr=True)
        logging.debug(update_dkt_db)

    def reload_metadata(self, el: AppImageListElement):
        if not (el.installed_status is InstalledStatus.INSTALLED):
            return
        
        logging.info(f'Reloading metadata for {el.file_path}')
        random_str = ''.join((random.choice('abcdxyzpqr123456789') for i in range(10)))
        dest_path = f'{self.extraction_folder}/gearlever_{random_str}'

        if not os.path.exists(dest_path):
            os.makedirs(dest_path)

        outdated_file = Gio.File.new_for_path(el.file_path)
        new_file = Gio.File.new_for_path(f'{dest_path}/tmp.appimage')

        gio_copy(outdated_file, new_file)

        self.uninstall(el)

        el.file_path = f'{dest_path}/tmp.appimage'
        el.extracted = None

        self.install_file(el)

    def get_appimage_generation(self, file: Gio.File) -> int:
        return self.supported_mimes.index(get_giofile_content_type(file)) + 1

    def create_list_element_from_file(self, file: Gio.File) -> AppImageListElement:
        if not self.can_install_file(file):
            raise InternalError(message='This file type is not supported')
        
        app_name: str = file.get_parse_name().split('/')[-1]

        el = AppImageListElement(
            name=re.sub('\.appimage$', '', app_name, 1, re.IGNORECASE),
            description='',
            version='md5: ' + get_file_hash(file),
            provider=self.name,
            installed_status=InstalledStatus.NOT_INSTALLED,
            file_path=file.get_path(),
            desktop_entry=None,
            local_file=True,
            generation=self.get_appimage_generation(file)
        )

        if self.is_installed(el):
            for installed in self.list_installed():
                if filecmp.cmp(installed.file_path, el.file_path, shallow=False):
                    return installed

        return el

    def extraction_folder_cleanup(self):
        logging.debug(f'Clearing {self.extraction_folder}')
        if os.path.exists(self.extraction_folder):
            shutil.rmtree(self.extraction_folder)


    def _extract_appimage(self, el: AppImageListElement) -> str:
        random_str = ''.join((random.choice('abcdxyzpqr123456789') for i in range(10)))
        dest_path = f'{self.extraction_folder}/gearlever_{random_str}'

        file = Gio.File.new_for_path(el.file_path)
        dest = Gio.File.new_for_path(f'{dest_path}/tmp.appimage')

        if not os.path.exists(f'{dest_path}'):
            os.makedirs(f'{dest_path}')

        logging.debug(f'Created temporary folder at {dest_path}')

        gio_copy(file, dest)

        ###############################################################################

        # The following code has been commented because uses appimage's built in extract method, 
        # however not all the appimages support it.
        #
        # Instead, we use p7zip to extract the content of the appimage bundle

        ###############################################################################
        
        # self._make_file_executable(el, dest.get_path())
        # appimage_extract_support = False


        # if el.generation == 2:
        #     try:
        #         appimage_help = subprocess.run([dest.get_path(), '--appimage-help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.decode()

        #         appimage_extract_support = ('-appimage-extract' in appimage_help)
        #         if not appimage_extract_support:
        #             raise InternalError('This appimage does not support appimage-extract')

        #     except Exception as e:
        #         logging.error(str(e))

        # if appimage_extract_support:
        #     prefix = [dest.get_path(), '--appimage-extract']
        #     extraction_output = ''

        #     # check if the appimage supports partial extraction 
        #     if '--appimage-extract [<pattern>]' in appimage_help:
        #         for match in ['*.desktop', 'usr/share/icons/*', '*.svg', '*.png']:
        #             run = [*prefix, match]

        #             extraction_output += terminal.sandbox_sh(run, cwd=dest_path)
        #     else:
        #         logging.debug('This AppImage does not support partial extraction, running ' + ' '.join(prefix))
        #         extraction_output += terminal.sandbox_sh([*prefix], cwd=dest_path)

        #     logging.debug(f'Extracted appimage {file.get_path()} with log:\n\n======\n\n{extraction_output}\n\n======\n\n')
        
        # else:
        # logging.info('This appiamge does not support appimage-extract, trying with 7z')
        logging.info('Exctracting with p7zip')
        z7zoutput = '=== 7z log ==='
        z7zoutput = '\n\n' + terminal.sandbox_sh(['7z', 'x', dest.get_path(), '-r', '*.png', '-osquashfs-root', '-y'], cwd=dest_path)
        z7zoutput += '\n\n' + terminal.sandbox_sh(['7z', 'x', dest.get_path(), '-r', '*.desktop', '-osquashfs-root', '-y'], cwd=dest_path)
        z7zoutput += '\n\n' + terminal.sandbox_sh(['7z', 'x', dest.get_path(), '-r', '*.svg', '-osquashfs-root', '-y'], cwd=dest_path)

        logging.debug(z7zoutput)

        return f'{dest_path}/squashfs-root'

    def _load_appimage_metadata(self, el: AppImageListElement) -> ExtractedAppImage:
        if not el.trusted:
            raise InternalError(message=_('Cannot load an untrusted AppImage'))
        
        if el.extracted:
            return el.extracted

        file = Gio.File.new_for_path(el.file_path)

        icon_file: Optional[Gio.File] = None
        desktop_file: Optional[Gio.File] = None
        desktop_entry: Optional[DesktopEntry.DesktopEntry] = None

        # hash file
        md5_hash = get_file_hash(file)
        temp_file_name = 'gearlever_appimage_' + md5_hash
        tmp_folder = Gio.File.new_for_path(f'{self.extraction_folder}/{temp_file_name}')

        if tmp_folder.query_exists():
            shutil.rmtree(tmp_folder.get_path())

        if tmp_folder.make_directory_with_parents(None):
            mounted_appimage_path = self._extract_appimage(el)
            extraction_folder = Gio.File.new_for_path(mounted_appimage_path)

            try:
                if not extraction_folder.query_exists():
                    raise InternalError('Missing mounted extraction folder')

                for d in  os.listdir(f'{extraction_folder.get_path()}'):
                    if not d.endswith('.desktop'):
                        continue

                    gdesk_file = Gio.File.new_for_path(f'{extraction_folder.get_path()}/{d}')
                    if get_giofile_content_type(gdesk_file) == 'application/x-desktop':
                        desktop_file = Gio.File.new_for_path(f'{tmp_folder.get_path()}/app.desktop')
                        gio_copy(file=gdesk_file, destination=desktop_file)

                        break

                desktop_entry_icon = None
                if desktop_file:
                    desktop_entry = DesktopEntry.DesktopEntry(desktop_file.get_path())
                    desktop_entry_icon = desktop_entry.getIcon()

                if desktop_entry_icon:
                    # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#the-filesystem-image


                    tmp_icon_file: Optional[Gio.File] = None
                    for icon_xt in ['.svg', '.png']:
                        icon_xt_f = Gio.File.new_for_path(extraction_folder.get_path() + f'/{desktop_entry_icon}{icon_xt}')

                        if icon_xt_f.query_exists():
                            tmp_icon_file = icon_xt_f
                            break

                    if icon_xt_f.get_path().endswith('.png'):
                        # always prefer svg(s) to png(s)
                        # if a png is not found in the root of the filesystem, try somewhere else

                        try_paths = [
                            extraction_folder.get_path() + f'/usr/share/icons/hicolor/scalable/apps/{desktop_entry_icon}.svg',
                            extraction_folder.get_path() + f'/usr/share/icons/hicolor/512x512/apps/{desktop_entry_icon}.png',
                            extraction_folder.get_path() + f'/usr/share/icons/hicolor/256x256/apps/{desktop_entry_icon}.png',
                            extraction_folder.get_path() + f'/usr/share/icons/hicolor/128x128/apps/{desktop_entry_icon}.png',
                            extraction_folder.get_path() + f'/usr/share/icons/hicolor/96x96apps/{desktop_entry_icon}.png'
                        ]

                        for icon_xt in try_paths:
                            logging.debug('Looking for icon in: ' + icon_xt)
                            icon_xt_f = Gio.File.new_for_path(icon_xt)

                            if icon_xt_f.query_exists():
                                tmp_icon_file = icon_xt_f
                                break

                    if tmp_icon_file:
                        icon_file = Gio.File.new_for_path(f'{tmp_folder.get_path()}/icon')
                        gio_copy(file=tmp_icon_file, destination=icon_file)

            except Exception as e:
                logging.error(str(e))

        result = ExtractedAppImage()
        result.desktop_entry = desktop_entry
        result.extraction_folder = tmp_folder.get_path()
        result.appimage_file = file
        result.desktop_file = desktop_file
        result.icon_file = icon_file
        result.md5 = md5_hash

        el.desktop_entry = desktop_entry
        el.extracted = result


        return result

    def _get_appimages_default_destination_path(self) -> str:
        return get_gsettings().get_string('appimages-default-folder').replace('~', GLib.get_home_dir())
    
    def _make_file_executable(self, el: AppImageListElement, file_path: str):
        if el.trusted:
            logging.debug('Chmod file ' + file_path)
            os.chmod(el.file_path, 0o755)
        else:
            raise InternalError(message=_('Cannot load an untrusted AppImage'))
