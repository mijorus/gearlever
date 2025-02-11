import logging
import re
import os
import shutil
import filecmp
import shlex
from xdg import DesktopEntry

import dataclasses
from ..lib import terminal
from ..models.AppListElement import AppListElement, InstalledStatus
from ..lib.async_utils import _async, idle
from ..lib.json_config import save_config_for_app, read_config_for_app
from ..lib.utils import get_giofile_content_type, get_gsettings, gio_copy, get_file_hash, \
    remove_special_chars, get_random_string, show_message_dialog, get_osinfo
from ..models.Models import AppUpdateElement, InternalError, DownloadInterruptedException
from typing import Optional, List, TypedDict
from gi.repository import GLib, Gtk, Gdk, Gio, Adw
from enum import Enum


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

class AppImageArchitecture:
    UNKNOWN = 'UNKNOWN'
    X86_64 = 'x86_64'
    ARM_64 = 'aarch64'

@dataclasses.dataclass
class AppImageListElement():
    name: str
    description: str
    provider: str
    installed_status: InstalledStatus
    file_path: str
    trusted: bool = False
    is_updatable_from_url = False
    env_variables: List[str] = dataclasses.field(default_factory=lambda: [])
    exec_arguments: List[str] = dataclasses.field(default_factory=lambda: [])
    desktop_entry: Optional[DesktopEntry.DesktopEntry] = None
    update_logic: Optional[AppImageUpdateLogic] = None
    architecture: Optional[AppImageArchitecture] = None
    updating_from: Optional[any] = None # AppImageListElement
    version: Optional[str] = None
    extracted: Optional[ExtractedAppImage] = None
    local_file: Optional[bool] = None
    external_folder: bool = False
    desktop_file_path: Optional[str] = None

    def set_installed_status(self, installed_status: InstalledStatus):
        self.installed_status = installed_status

    def set_trusted(self):
        logging.debug('Chmod file ' + self.file_path)
        os.chmod(self.file_path, 0o755)
        self.trusted = True


class AppImageProvider():
    supported_mimes = ['application/x-iso9660-appimage', 'application/vnd.appimage']
    
    def __init__(self):
        self.name = 'AppImage'
        self.v2_detector_string = 'AppImages require FUSE to run.'
        self.icon = "/it/mijorus/gearlever/assets/App-image-logo.png"
        self.desktop_exec_codes = ["%f", "%F",  "%u",  "%U",  "%i",  "%c", "%k"]
        logging.info(f'Activating {self.name} provider')


        self.general_messages = []
        self.update_messages = []

        self.extraction_folder = GLib.get_tmp_dir() + '/it.mijorus.gearlever/appimages'
        self.user_desktop_files_path = f'{GLib.get_home_dir()}/.local/share/applications'
        self.user_local_share_path = f'{GLib.get_home_dir()}/.local/share/'

    def list_installed(self) -> list[AppImageListElement]:
        default_folder_path = self._get_appimages_default_destination_path()
        manage_from_outside = get_gsettings().get_boolean('manage-files-outside-default-folder')
        output = []

        if not os.path.exists(self.user_desktop_files_path):
            return output

        for file_name in os.listdir(self.user_desktop_files_path):
            gfile = Gio.File.new_for_path(
                os.path.join(self.user_desktop_files_path, file_name))

            try:
                if os.path.isfile(gfile.get_path()) and get_giofile_content_type(gfile) == 'application/x-desktop':
                    entry = DesktopEntry.DesktopEntry(filename=gfile.get_path())
                    exec_location = entry.getTryExec()
                    exec_index = entry.getExec().find(exec_location)

                    exec_tokens = []
                    env_variables = []
                    if exec_index >= 0:
                        after_exec = entry.getExec()[exec_index:]
                        before_exec = entry.getExec()[:exec_index]

                        exec_tokens = shlex.split(after_exec)[1:]
                        before_exec_tokens = shlex.split(before_exec)

                        if before_exec and before_exec_tokens[0] == 'env':
                            [env_variables.append(v) for v in before_exec_tokens[1:]]

                    if os.path.isfile(exec_location):
                        exec_gfile = Gio.File.new_for_path(exec_location)
                        exec_in_defalut_folder = os.path.isfile(
                                os.path.join(default_folder_path, exec_gfile.get_basename()))
                        exec_in_folder = True if manage_from_outside else exec_in_defalut_folder

                        if exec_in_folder and self.can_install_file(exec_gfile):
                            list_element = AppImageListElement(
                                name=entry.getName(),
                                desktop_file_path=gfile.get_path(),
                                description=entry.getComment(),
                                version=entry.get('X-AppImage-Version'),
                                installed_status=InstalledStatus.INSTALLED,
                                file_path=exec_location,
                                provider=self.name,
                                desktop_entry=entry,
                                trusted=True,
                                external_folder=(not exec_in_defalut_folder),
                                exec_arguments=exec_tokens,
                                env_variables=env_variables,
                            )

                            list_element.architecture = self.get_elf_arch(list_element)

                            output.append(list_element)
                        else:
                            logging.debug(f'{gfile.get_path()} skipped because {exec_location} is not a supported file type')
                    else:
                        logging.debug(f'{gfile.get_path()} skipped because {exec_location} does not exists on the filesystem')

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

            extracted = self._load_appimage_metadata(el)

            if extracted.icon_file and os.path.exists(extracted.icon_file.get_path()):
                return Gtk.Image.new_from_file(extracted.icon_file.get_path())

        return Gtk.Image(icon_name='gl-application-x-executable-symbolic')

    def get_description(self, el: AppImageListElement) -> str:
        if el.desktop_entry:
            return el.desktop_entry.getComment()
        
        return ''

    def refresh_title(self, el: AppImageListElement):
        if el.desktop_entry:
            el.name = el.desktop_entry.getName()
        
        extracted = self._load_appimage_metadata(el)
        if extracted.desktop_entry:
            el.name = extracted.desktop_entry.getName()
            el.version = el.desktop_entry.get('X-AppImage-Version')

    def uninstall(self, el: AppImageListElement, force_delete=False):
        logging.info(f'Removing {el.file_path}')

        gf = Gio.File.new_for_path(el.file_path)

        if force_delete:
            os.remove(el.file_path)
        else:
            try:
                logging.info(f'Trashing {el.file_path}')
                gf.trash(None)
            except Exception as e:
                logging.warn(f'Trashing {el.file_path} failed! Removing it instead...')
                logging.warn(e)
                os.remove(el.file_path)

        if el.desktop_entry:
            logging.info(f'Removing {el.desktop_entry.getFileName()}')
            os.remove(el.desktop_entry.getFileName())

        icon = el.desktop_entry.getIcon()
        if '/' in icon and os.path.isfile(icon):
            os.remove(icon)

        el.set_installed_status(InstalledStatus.NOT_INSTALLED)

    def search(self, query: str) -> list[AppListElement]:
        return []

    def get_long_description(self, el: AppListElement) -> str:
        return ''

    def run(self, el: AppImageListElement):
        if el.trusted:
            if el.installed_status is InstalledStatus.INSTALLED:
                gtk_launch = False

                try:
                    terminal.host_sh(['which', 'gtk-launch'])
                    gtk_launch = True
                except Exception as e:
                    logging.warning('gtk-launch is missing, falling back to executable launch')

                if gtk_launch and el.desktop_file_path:
                    desktop_file_name = os.path.basename(el.desktop_file_path)
                    terminal.host_threaded_sh(['gtk-launch', desktop_file_name], callback=self._check_launch_output, return_stderr=True)
                else:
                    self._run_from_desktopentry(el)
            else:
                self._run_filepath(el)

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
            version = self._get_app_version(extracted_appimage)
            dest_file_info = extracted_appimage.appimage_file.query_info('*', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)

            # Move .appimage to its default location
            appimages_destination_path = self._get_appimages_default_destination_path()

            if not os.path.exists(f'{appimages_destination_path}'):
                os.mkdir(f'{appimages_destination_path}')

            # how the appimage will be called
            appimage_filename = ''
            prefixed_filename = ''
            if el.update_logic == AppImageUpdateLogic.REPLACE:
                appimage_filename = os.path.basename(el.updating_from.file_path)
                desktop_file_path = os.path.basename(el.updating_from.desktop_file_path)
                prefixed_filename = os.path.splitext(desktop_file_path)[0]
            else:
                appimage_filename = f'gearlever_{dest_file_info.get_name()}'
                if extracted_appimage.desktop_entry:
                    appimage_filename = extracted_appimage.desktop_entry.getName()
                    appimage_filename = appimage_filename.lower().replace(' ', '_')
                
                prefixed_filename = re.sub(r"[^A-Za-z0-9_]+", "", appimage_filename).lower()
                appimage_filename = prefixed_filename

                append_file_ext = True
                gsettings = get_gsettings()

                if extracted_appimage.desktop_entry and \
                    gsettings.get_boolean('exec-as-name-for-terminal-apps') and \
                        extracted_appimage.desktop_entry.getTerminal():

                    exec_name = shlex.split(extracted_appimage.desktop_entry.getExec())[0]
                    appimage_filename = exec_name

                    if appimage_filename == 'AppDir':
                        appimage_filename = extracted_appimage.desktop_entry.getName()
                        appimage_filename = appimage_filename.lower()

                    append_file_ext = False

                # if there is already an app with the same name, 
                # we try not to overwrite

                if append_file_ext:
                    appimage_filename = appimage_filename + '.appimage'

                app_name_without_ext = os.path.splitext(appimage_filename)[0]
                app_name_without_ext = remove_special_chars(app_name_without_ext)
                appimage_filename = remove_special_chars(appimage_filename)

                i = 0
                files_in_dest_dir = os.listdir(self._get_appimages_default_destination_path())
                while appimage_filename in files_in_dest_dir:
                    if i == 0:
                        appimage_filename = app_name_without_ext + '_' + version.replace('.', '_')
                    else:
                        appimage_filename = app_name_without_ext + f'_{i}'

                    if append_file_ext:
                        appimage_filename = appimage_filename + '.appimage'

                    i += 1

            dest_appimage_file = Gio.File.new_for_path(appimages_destination_path + '/' + appimage_filename)

            if not gio_copy(extracted_appimage.appimage_file, dest_appimage_file):
                raise InternalError('Error while moving appimage file to the destination folder')

            logging.debug(f'file copied to {appimages_destination_path}')

            el.file_path = dest_appimage_file.get_path()
            el.set_trusted()

            # copy the icon file
            icon_file = None
            dest_appimage_icon_file = None
            if extracted_appimage.desktop_entry:
                icon_file = extracted_appimage.icon_file

            if icon_file and os.path.exists(icon_file.get_path()):
                if not os.path.exists(f'{appimages_destination_path}/.icons'):
                    os.mkdir(f'{appimages_destination_path}/.icons')

                i, icon_file_ext = os.path.splitext(icon_file.get_path())
                dest_appimage_icon_file = Gio.File.new_for_path(
                    f'{appimages_destination_path}/.icons/{prefixed_filename}{icon_file_ext}')

                gio_copy(icon_file, dest_appimage_icon_file)

            # Move .desktop file to its default location
            if not os.path.exists(self.user_desktop_files_path):
                os.makedirs(self.user_desktop_files_path)

            dest_desktop_file_path = f'{self.user_desktop_files_path}/{prefixed_filename}.desktop'
            dest_desktop_file_path = dest_desktop_file_path.replace(' ', '_')

            # Get default exec arguments
            exec_arguments = shlex.split(extracted_appimage.desktop_entry.getExec())[1:]
            el.exec_arguments = exec_arguments

            with open(extracted_appimage.desktop_file.get_path(), 'r') as dskt_file:
                desktop_file_content = dskt_file.read()
                desktop_file_content = re.sub(r'^TryExec=.*$', "", desktop_file_content, flags=re.MULTILINE)
                desktop_file_content = re.sub(r'^Icon=.*$', "", desktop_file_content, flags=re.MULTILINE)

                # replace executable path
                exec_command = ['Exec=' + shlex.join([dest_appimage_file.get_path(), *exec_arguments])]
                # replace try exec executable path
                exec_command.append(f'TryExec={dest_appimage_file.get_path()}')

                if dest_appimage_icon_file:
                    exec_command.append(f"Icon={dest_appimage_icon_file.get_path()}")
                else:
                    exec_command.append(f'Icon=applications-other')

                desktop_file_content = re.sub(
                    r'^Exec=.*$',
                    '\n'.join(exec_command),
                    desktop_file_content,
                    flags=re.MULTILINE
                )

                # generate a new app name
                final_app_name = extracted_appimage.appimage_file.get_basename()
                if extracted_appimage.desktop_entry:
                    final_app_name = extracted_appimage.desktop_entry.getName()
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
                if (not os.path.exists(self.user_desktop_files_path)) and os.path.exists(self.user_local_share_path):
                    os.mkdir(self.user_desktop_files_path)

                with open(dest_desktop_file_path, 'w+') as desktop_file_python_dest:
                    desktop_file_python_dest.write(desktop_file_content)

            if os.path.exists(dest_desktop_file_path):
                el.desktop_entry = DesktopEntry.DesktopEntry(filename=dest_desktop_file_path)
                el.desktop_file_path = dest_desktop_file_path
                el.installed_status = InstalledStatus.INSTALLED

            if el.updating_from and el.updating_from.env_variables:
                el.env_variables = el.updating_from.env_variables
                self.update_desktop_file(el)

        except Exception as e:
            logging.error('Appimage installation error: ' + str(e))
            raise e

        if get_gsettings().get_boolean('move-appimage-on-integration'):
            logging.info('Deleting original appimage file from: '  + extracted_appimage.appimage_file.get_path())
            if not extracted_appimage.appimage_file.delete(None):
                raise InternalError('Cannot delete original file')

        update_dkt_db = terminal.host_sh(['update-desktop-database', self.user_desktop_files_path, '-v'], return_stderr=True)
        logging.debug(update_dkt_db)

        el.updating_from = None

    def reload_metadata(self, el: AppImageListElement):
        if not (el.installed_status is InstalledStatus.INSTALLED):
            return
        
        logging.info(f'Reloading metadata for {el.file_path}')
        random_str = get_random_string()
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

    def get_appimage_type(self, el: AppImageListElement) -> str:
        # https://github.com/AppImage/AppImageSpec/blob/fb05d9e1b8b8616dbeb7491303edc537dca573f3/draft.md#type-1-image-format

        appimage_type = 0
        with open(el.file_path, 'rb') as f:
            magic = f.read(11)[-3:]

            if magic == b'\x41\x49\x01':  # 0x414901
                appimage_type = 1
            elif magic == b'\x41\x49\x02':  # 0x414902
                appimage_type = 2

        return str(appimage_type)

    def create_list_element_from_file(self, file: Gio.File) -> AppImageListElement:
        if not self.can_install_file(file):
            raise InternalError(message='This file type is not supported')
        
        app_name: str = file.get_parse_name().split('/')[-1]

        el = AppImageListElement(
            name=re.sub(r'\.appimage$', '', app_name, 1, re.IGNORECASE),
            description='',
            version='',
            provider=self.name,
            installed_status=InstalledStatus.NOT_INSTALLED,
            file_path=file.get_path(),
            desktop_entry=None,
            local_file=True,
        )

        el.architecture = self.get_elf_arch(el)

        if self.is_installed(el):
            for installed in self.list_installed():
                if filecmp.cmp(installed.file_path, el.file_path, shallow=False):
                    return installed

        return el

    def extraction_folder_cleanup(self):
        logging.debug(f'Clearing {self.extraction_folder}')
        if os.path.exists(self.extraction_folder):
            shutil.rmtree(self.extraction_folder)
            os.makedirs(self.extraction_folder)

    def update_exec_arguments(self, el:AppImageListElement, arg_string: str):
        arg_string = arg_string.replace("\n", "")

        if not el.desktop_file_path:
            raise Exception('desktop_file_path not specified')
    
        desktop_file_content = ''
        entry = DesktopEntry.DesktopEntry(filename=el.desktop_file_path)
        with open(el.desktop_file_path, 'r') as desktop_file:
            desktop_file_content = desktop_file.read()
            exec_command = shlex.split(entry.getExec())[0]
            exec_command += f' {arg_string}'

            # replace executable path
            desktop_file_content = re.sub(
                r'^Exec=.*$',
                f"Exec={exec_command}",
                desktop_file_content,
                flags=re.MULTILINE
            )

        with open(el.desktop_file_path, 'w') as desktop_file:
            desktop_file.write(desktop_file_content)         

    def update_desktop_file(self, el: AppImageListElement):
        if not el.desktop_file_path:
            raise Exception('desktop_file_path not specified')
    
        desktop_file_content = ''
        entry = DesktopEntry.DesktopEntry(filename=el.desktop_file_path)
        with open(el.desktop_file_path, 'r') as desktop_file:
            desktop_file_content = desktop_file.read()

            tryexec_command = entry.getTryExec()
            exec_arguments = ' '.join(el.exec_arguments)
            env_vars = ' '.join(el.env_variables)

            if exec_arguments:
                exec_arguments = f' {exec_arguments}'

            if env_vars:
                env_vars = f'env {env_vars} '

            exec_command = f'{env_vars}{tryexec_command}{exec_arguments}'

            # replace executable path
            desktop_file_content = re.sub(
                r'^Exec=.*$',
                f"Exec={exec_command}",
                desktop_file_content,
                flags=re.MULTILINE
            )

        with open(el.desktop_file_path, 'w') as desktop_file:
            desktop_file.write(desktop_file_content)

        el.desktop_entry = DesktopEntry.DesktopEntry(filename=el.desktop_file_path)

    def update_from_url(self, manager, el: AppImageListElement, status_cb: callable) -> AppImageListElement:
        try:
            update_file_path, f_hash = manager.download(status_cb)
        except DownloadInterruptedException as de:
            return el
        except Exception as e:
            raise e

        update_gfile = Gio.file_new_for_path(update_file_path)

        if not self.can_install_file(update_gfile):
            raise Exception(_('The downloaded file is not a valid appimage, please check if the provided URL is correct'))
        
        list_element = self.create_list_element_from_file(update_gfile)
        self.refresh_title(list_element)

        if not manager.embedded and not self.is_updatable(list_element):
            raise Exception(_(f'The downloaded appimage does not have the same app name and can\'t be updated\n{el.name} ➔ {list_element.name}'))
        
        list_element.update_logic = AppImageUpdateLogic.REPLACE
        list_element.updating_from = el
        self.install_file(list_element)

        list_element.updating_from = None
        list_element.update_logic = None

        return list_element

    # Private methods
    def _run_filepath(self, el: AppImageListElement):
        is_nixos = re.search(r"^NAME=NixOS$", get_osinfo(), re.MULTILINE) != None

        if is_nixos:
            self._nixos_checks()
            terminal.host_threaded_sh(['appimage-run', el.file_path], callback=self._check_launch_output, return_stderr=True)
            return

        exec_args = []
        if el.desktop_entry:
            exec_args = shlex.split(el.desktop_entry.getExec())[1:]
            exec_args = [i for i in exec_args if i not in self.desktop_exec_codes]

        terminal.host_threaded_sh([el.file_path, *exec_args], callback=self._check_launch_output, return_stderr=True)

    def _run_from_desktopentry(self, el: AppImageListElement):
        is_nixos = re.search(r"^NAME=NixOS$", get_osinfo(), re.MULTILINE) != None

        if is_nixos:
            self._nixos_checks()
            cmd = ['appimage-run', el.desktop_entry.getTryExec()]
            return

        cmd = shlex.split(el.desktop_entry.getExec())
        cmd = [i for i in cmd if i not in self.desktop_exec_codes]

        terminal.host_threaded_sh(cmd, callback=self._check_launch_output, return_stderr=True)

    def _nixos_checks(self):
        try:
            terminal.host_sh(['which', 'appimage-run'])
        except Exception as e:
            msg = _("Running AppImages on NixOS requires appimage-run")
            raise Exception(msg)

    @idle
    def _check_launch_output(self, output: str):
        output = output.strip()

        if output:
            # Printing the output might help folks who run 
            # run Gear Lever from the terminal
            print(output)

            if self.v2_detector_string in output:
                show_message_dialog(
                    _('Error'),
                    _('AppImages require FUSE to run. You might still be able to run it with --appimage-extract-and-run in the command line arguments. \n\nClick the link below for more information. \n{url}'.format(
                        url='<a href="https://github.com/AppImage/AppImageKit/wiki/FUSE">https://github.com/AppImage/AppImageKit/wiki/FUSE</a>'
                    )),
                    markup=True
                )

    def _extract_appimage(self, el: AppImageListElement) -> str:
        random_str = get_random_string()
        dest_path = os.path.join(self.extraction_folder, f'gearlever_{random_str}')

        file = Gio.File.new_for_path(el.file_path)

        if not os.path.exists(f'{dest_path}'):
            os.makedirs(f'{dest_path}')

        logging.debug(f'Created temporary folder at {dest_path}')

        ###############################################################################

        # We use p7zip to extract the content of the appimage bundle
        # Old versions of Gear Lever used the --appimage-extract command, which is not
        # supported by all the appimage packages

        ###############################################################################

        squashfs_root_folder = os.path.join(dest_path, 'squashfs-root')
        logging.info(f'Exctracting with p7zip to {squashfs_root_folder}')
        logging.info('\n\n=== 7z log ===')
        z7zoutput = terminal.sandbox_sh(['7z', 'x', file.get_path(), f'-o{squashfs_root_folder}', '-y', '-bso0', '-bsp0', 
                                                  '*.png', '*.svg', '*.desktop', '.DirIcon', '-r'], cwd=dest_path, return_stderr=True)

        logging.debug(f'{z7zoutput}=== end 7z log ===\n')
        return squashfs_root_folder

    def _load_appimage_metadata(self, el: AppImageListElement) -> ExtractedAppImage:
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
                    raise InternalError('Missing mounted extraction folder', mounted_appimage_path)

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
                    desktop_entry_icon = re.sub(r"\.(png|svg)$", '', desktop_entry_icon)

                if desktop_entry_icon:
                    # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#the-filesystem-image

                    tmp_icon_file: Optional[Gio.File] = None
                    icon_xt_f = None
                    for icon_xt in ['.svg', '.png']:
                        icon_xt_f = Gio.File.new_for_path(extraction_folder.get_path() + f'/{desktop_entry_icon}{icon_xt}')

                        if icon_xt_f.query_exists():
                            tmp_icon_file = icon_xt_f
                            break

                    if (not icon_xt_f.query_exists()) or (get_giofile_content_type(icon_xt_f) not in ['image/svg+xml', 'image/svg']):
                        # always prefer svg(s) to png(s)
                        # if a png is not found in the root of the filesystem, try somewhere else

                        icons_folder_prefix = '/usr/share/icons/hicolor'
                        icon_try_paths = [
                            extraction_folder.get_path() + f'{icons_folder_prefix}/scalable/apps/{desktop_entry_icon}.svg',
                            extraction_folder.get_path() + f'{icons_folder_prefix}/512x512/apps/{desktop_entry_icon}.png',
                            extraction_folder.get_path() + f'{icons_folder_prefix}/256x256/apps/{desktop_entry_icon}.png',
                            extraction_folder.get_path() + f'{icons_folder_prefix}/128x128/apps/{desktop_entry_icon}.png',
                            extraction_folder.get_path() + f'{icons_folder_prefix}/96x96/apps/{desktop_entry_icon}.png'
                        ]

                        for icon_xt in icon_try_paths:
                            logging.debug('Looking for icon in: ' + icon_xt)
                            icon_xt_f = Gio.File.new_for_path(icon_xt)

                            if icon_xt_f.query_exists():
                                tmp_icon_file = icon_xt_f
                                break
                    if not tmp_icon_file:
                        # if icon file is still not found, let's try with .DirIcon file
                        diricon = Gio.File.new_for_path(
                            os.path.join(extraction_folder.get_path(), '.DirIcon')
                        )

                        if diricon.query_exists():
                            diricon_ct = get_giofile_content_type(diricon)

                            if diricon_ct in ['image/png']:
                                tmp_icon_file = diricon
                            elif diricon_ct in ['text/plain']:
                                with open(diricon.get_path(), 'r') as f:
                                    possible_icon_path = f.read()
                                    diricon_linked_to = Gio.File.new_for_path(possible_icon_path)

                                    if diricon_linked_to.query_exists() and \
                                        get_giofile_content_type(diricon_linked_to) in ['image/png']:
                                        tmp_icon_file = diricon_linked_to

                    if tmp_icon_file:
                        i, tmp_icon_ext = os.path.splitext(tmp_icon_file.get_path())
                        icon_file = Gio.File.new_for_path(f'{tmp_folder.get_path()}/icon{tmp_icon_ext}')
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

    def _get_app_version(self, extracted_appimage: ExtractedAppImage):
        version = None

        if extracted_appimage.desktop_entry:
            version = extracted_appimage.desktop_entry.get('X-AppImage-Version')

        if not version:
            version = extracted_appimage.md5[0:6]

        return version
    
    def get_elf_arch(self, el: AppImageListElement) -> AppImageArchitecture:
        file_brief = terminal.sandbox_sh(['file', '--brief', '--exclude-quiet=apptype', '--exclude-quiet=ascii',
                                                     '--exclude-quiet=compress', '--exclude-quiet=csv', '--exclude-quiet=elf', 
                                                     '--exclude-quiet=encoding', '--exclude-quiet=tar', '--exclude-quiet=cdf',
                                                     '--exclude-quiet=json', '--exclude-quiet=simh', '--exclude-quiet=text', '--exclude-quiet=tokens',
                                                     el.file_path])
                        
        aarch = AppImageArchitecture.UNKNOWN
        file_brief = file_brief.lower()
        
        if 'aarch64' in file_brief or ' arm ' in file_brief:
            aarch = AppImageArchitecture.ARM_64
        elif 'x86-64' in file_brief or 'x86_64' in file_brief:
            aarch = AppImageArchitecture.X86_64

        return aarch
