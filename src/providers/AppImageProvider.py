import logging
import glob
import re
import os
import shutil
import filecmp
import shlex
from xdg import DesktopEntry
from desktop_entry_lib import DesktopEntry as JdDesktopEntry

import dataclasses
from ..models.Settings import Settings
from ..models.AppListElement import InstalledStatus
from ..lib.constants import TMP_DIR
from ..lib import terminal
from ..lib.async_utils import idle
from ..lib.ini_config import Config
from ..lib.launchers import desktop_id_from_filename, launcher_filename_part, pick_primary_launcher
from ..lib.utils import get_giofile_content_type, gio_copy, get_file_hash, \
    remove_special_chars, get_random_string, get_osinfo, extract_terminal_arguments, show_message_dialog, gnu_naturalsize
from ..models.Models import InternalError, DownloadInterruptedException
from typing import Optional, List, TypedDict
from gi.repository import GLib, Gtk, Gdk, Gio
from enum import Enum


@dataclasses.dataclass
class ExtractedLauncher:
    """A .desktop file shipped inside an AppImage.
    The first launcher of ``ExtractedAppImage.launchers`` is the primary one.
    """
    desktop_id: str
    name: str
    desktop_file: Gio.File
    desktop_entry: DesktopEntry.DesktopEntry
    icon_file: Optional[Gio.File] = None


@dataclasses.dataclass
class AppImageLauncher:
    """A .desktop file installed by Gear Lever for an AppImage.
    ``AppImageListElement.launchers[0]`` is always the primary launcher.
    """
    name: str
    desktop_file_path: str
    desktop_entry: Optional[DesktopEntry.DesktopEntry] = None
    exec_arguments: str = ''
    icon_file_path: Optional[str] = None


class ExtractedAppImage():
    extraction_folder: str
    desktop_entry: Optional[DesktopEntry.DesktopEntry]
    appimage_file: Gio.File
    launchers: List[ExtractedLauncher]
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
    exec_arguments: str = ''
    desktop_entry: Optional[DesktopEntry.DesktopEntry] = None
    update_logic: Optional[AppImageUpdateLogic] = None
    architecture: Optional[AppImageArchitecture] = None
    updating_from: Optional[any] = None # AppImageListElement
    version: Optional[str] = None
    extracted: Optional[ExtractedAppImage] = None
    local_file: Optional[bool] = None
    external_folder: bool = False
    desktop_file_path: Optional[str] = None
    launchers: List[AppImageLauncher] = dataclasses.field(default_factory=lambda: [])
    size: int = 0

    def set_installed_status(self, installed_status: InstalledStatus):
        self.installed_status = installed_status

    def set_trusted(self):
        logging.debug('Chmod file ' + self.file_path)
        os.chmod(self.file_path, 0o755)
        self.trusted = True

    def get_config(self):
        return Config.get_app_config(self)

class AppImageProvider():
    # https://cgit.freedesktop.org/xdg/shared-mime-info/tree/data/freedesktop.org.xml.in#n2114
    supported_mimes = ['application/x-iso9660-appimage', 'application/vnd.appimage', 'application/x-appimage',
                    'application/vnd.efi.iso']

    def __init__(self):
        self.name = 'AppImage'
        self.v2_detector_string = 'AppImages require FUSE to run.'
        self.icon = "/it/mijorus/gearlever/assets/App-image-logo.png"
        self.desktop_exec_codes = ["%f", "%F",  "%u",  "%U",  "%i",  "%c", "%k"]
        logging.info(f'Activating {self.name} provider')

        self.general_messages = []
        self.update_messages = []

        self.extraction_folder = os.path.join(TMP_DIR, 'appimages')
        self.user_desktop_files_path = os.path.join(GLib.get_home_dir(), '.local', 'share', 'applications')
        self.user_local_share_path = os.path.join(GLib.get_home_dir(), '.local', 'share')
    desk_entry_section_regex = re.compile(r'\[Desktop Entry\][\s\S]*?(?=\n\[)', flags=re.MULTILINE)

    def list_installed(self) -> list[AppImageListElement]:
        default_folder_path = self._get_appimages_default_destination_path()
        manage_from_outside = Settings.settings.get_boolean('manage-files-outside-default-folder')
        output = []

        if not os.path.exists(self.user_desktop_files_path):
            return output

        # An AppImage can ship more than one launcher, so several .desktop
        # files can point to the same executable. Keep them grouped under a
        # single list element, otherwise the app would show up once per
        # launcher and removing one entry would delete the shared AppImage.
        elements_by_appimage: dict[str, AppImageListElement] = {}

        for file_name in sorted(os.listdir(self.user_desktop_files_path)):
            gfile = Gio.File.new_for_path(
                os.path.join(self.user_desktop_files_path, file_name))

            try:
                if not (os.path.isfile(gfile.get_path()) and get_giofile_content_type(gfile) == 'application/x-desktop'):
                    continue

                entry = DesktopEntry.DesktopEntry(filename=gfile.get_path())
                exec_location = entry.getTryExec()
                exec_command_data = extract_terminal_arguments(entry.getExec())
                exec_arguments = ' '.join(exec_command_data['arguments'])

                if not os.path.isfile(exec_location):
                    logging.debug(f'{gfile.get_path()} skipped because {exec_location} does not exists on the filesystem')
                    continue

                exec_gfile = Gio.File.new_for_path(exec_location)
                exec_in_defalut_folder = os.path.isfile(
                        os.path.join(default_folder_path, exec_gfile.get_basename()))
                exec_in_folder = True if manage_from_outside else exec_in_defalut_folder

                if not (exec_in_folder and self.can_install_file(exec_gfile)):
                    logging.debug(f'{gfile.get_path()} skipped because {exec_location} is not a supported file type')
                    continue

                launcher = AppImageLauncher(
                    name=entry.getName(),
                    desktop_file_path=gfile.get_path(),
                    desktop_entry=entry,
                    exec_arguments=exec_arguments,
                    icon_file_path=entry.getIcon(),
                )

                list_element = elements_by_appimage.get(exec_location)

                if not list_element:
                    app_version = self._get_app_version(None, desktop_entry=entry, return_hash=False)
                    file_size = os.stat(exec_location).st_size

                    list_element = AppImageListElement(
                        name=entry.getName(),
                        desktop_file_path=gfile.get_path(),
                        description=entry.getComment(),
                        version=(app_version or None),
                        installed_status=InstalledStatus.INSTALLED,
                        file_path=exec_location,
                        provider=self.name,
                        desktop_entry=entry,
                        trusted=True,
                        external_folder=(not exec_in_defalut_folder),
                        exec_arguments=exec_arguments,
                        env_variables=exec_command_data['env_vars'],
                        size=file_size,
                    )

                    list_element.architecture = None
                    elements_by_appimage[exec_location] = list_element

                list_element.launchers.append(launcher)

            except Exception as e:
                logging.warn(e)

        for list_element in elements_by_appimage.values():
            self._set_primary_launcher(list_element)
            output.append(list_element)

        return output

    def _set_primary_launcher(self, el: AppImageListElement):
        """Move the launcher that represents the app to the front."""
        if not el.launchers:
            return

        primary_index = pick_primary_launcher(
            os.path.basename(el.file_path),
            [(desktop_id_from_filename(launcher.desktop_file_path), launcher.name)
             for launcher in el.launchers]
        )

        el.launchers.insert(0, el.launchers.pop(primary_index))
        primary = el.launchers[0]

        el.desktop_file_path = primary.desktop_file_path
        el.desktop_entry = primary.desktop_entry
        el.name = primary.name
        el.exec_arguments = primary.exec_arguments

        if primary.desktop_entry:
            el.description = primary.desktop_entry.getComment()
            el.env_variables = extract_terminal_arguments(primary.desktop_entry.getExec())['env_vars']
            el.version = self._get_app_version(None, desktop_entry=primary.desktop_entry, return_hash=False) or None

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

    def refresh_data(self, el: AppImageListElement):
        if el.desktop_entry:
            el.name = el.desktop_entry.getName()

        extracted = self._load_appimage_metadata(el)
        if extracted.desktop_entry:
            el.name = extracted.desktop_entry.getName()
            el.version = el.desktop_entry.get('X-AppImage-Version')

    def refresh_arch(self, el: AppImageListElement):
        el.architecture = self.get_elf_arch(el)

    def uninstall(self, el: AppImageListElement, force_delete=False, remove_configuration=True):
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

        for desktop_file_path in self._get_element_desktop_files(el):
            logging.info(f'Removing {desktop_file_path}')

            try:
                os.remove(desktop_file_path)
            except FileNotFoundError:
                pass
            except Exception as e:
                logging.warning(f'Cannot remove {desktop_file_path}: {e}')

        for icon_path in self._get_element_icon_files(el):
            logging.info(f'Removing {icon_path}')

            try:
                os.remove(icon_path)
            except FileNotFoundError:
                pass
            except Exception as e:
                logging.warning(f'Cannot remove {icon_path}: {e}')

        if remove_configuration:
            Config.delete_app_update_config(el)

        el.set_installed_status(InstalledStatus.NOT_INSTALLED)
        Config.delete_app_config(el)
        Config.delete_app_update_config(el)

    def _get_element_desktop_files(self, el: AppImageListElement) -> list[str]:
        desktop_files = [launcher.desktop_file_path
                         for launcher in el.launchers if launcher.desktop_file_path]

        if not desktop_files and el.desktop_file_path:
            desktop_files = [el.desktop_file_path]

        return list(dict.fromkeys(desktop_files))

    def _get_element_icon_files(self, el: AppImageListElement) -> list[str]:
        """Icon files Gear Lever copied for this app, ignoring theme icon names."""
        allowed_folders = {
            os.path.realpath(os.path.join(
                self._get_appimages_default_destination_path(), '.icons'
            )),
        }

        if el.file_path:
            allowed_folders.add(os.path.realpath(os.path.join(
                os.path.dirname(el.file_path), '.icons'
            )))

        # Every installed launcher records the icon it points at
        icon_paths = [launcher.icon_file_path for launcher in el.launchers]

        if not icon_paths and el.desktop_entry:
            icon_paths = [el.desktop_entry.getIcon()]

        result = []

        # Only ever delete icons that Gear Lever copied inside its own folder
        for icon_path in icon_paths:
            if not icon_path or '/' not in icon_path:
                continue

            if os.path.dirname(os.path.realpath(icon_path)) not in allowed_folders:
                continue

            if os.path.isfile(icon_path):
                result.append(icon_path)

        return list(dict.fromkeys(result))

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
        None
        appimages_destination_path = self._get_appimages_default_destination_path()

        try:
            extracted_appimage = self._load_appimage_metadata(el)

            if not extracted_appimage.launchers:
                raise InternalError(_('This AppImage does not contain any .desktop file'))

            version = self._get_app_version(extracted_appimage, return_hash=False)
            dest_file_info = extracted_appimage.appimage_file.query_info('*', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)

            # Move .appimage to its default location
            if not os.path.exists(f'{appimages_destination_path}'):
                os.mkdir(f'{appimages_destination_path}')

            # how the appimage will be called
            appimage_filename = ''
            prefixed_filename = ''
            if el.update_logic == AppImageUpdateLogic.REPLACE and el.updating_from is not None:
                appimage_filename = os.path.basename(el.updating_from.file_path)
                desktop_file_path = os.path.basename(el.updating_from.desktop_file_path)
                prefixed_filename = os.path.splitext(desktop_file_path)[0]
            else:
                dest_file_info_name = os.path.splitext(dest_file_info.get_name())[0]
                appimage_filename = f'gearlever_{dest_file_info_name}'

                if extracted_appimage.desktop_entry:
                    appimage_filename = extracted_appimage.desktop_entry.getName()
                    appimage_filename = appimage_filename.lower().replace(' ', '_')

                append_file_ext = True
                gsettings = Settings.settings

                if extracted_appimage.desktop_entry and \
                    gsettings.get_boolean('exec-as-name-for-terminal-apps') and \
                        extracted_appimage.desktop_entry.getTerminal():

                    append_file_ext = False
                    if appimage_filename == 'AppDir':
                        appimage_filename = extracted_appimage.desktop_entry.getName()

                if append_file_ext:
                    appimage_filename = f'{appimage_filename}.appimage'

                app_name_without_ext = appimage_filename
                appimage_filename = remove_special_chars(appimage_filename).lower()

                i = 0
                files_in_dest_dir = os.listdir(self._get_appimages_default_destination_path())

                # if there is already an app with the same name,
                # we try not to overwrite
                while appimage_filename in files_in_dest_dir:
                    if i == 0 and version:
                        appimage_filename = app_name_without_ext + '_' + version.replace('.', '_')
                    else:
                        appimage_filename = app_name_without_ext + f'_{i}'

                    if append_file_ext:
                        appimage_filename = appimage_filename + '.appimage'

                    i += 1

                prefixed_filename = os.path.splitext(appimage_filename)[0]

            dest_appimage_file = Gio.File.new_for_path(
                os.path.join(appimages_destination_path, appimage_filename))

            if not gio_copy(extracted_appimage.appimage_file, dest_appimage_file):
                raise InternalError('Error while moving appimage file to the destination folder')

            logging.debug(f'file copied to {appimages_destination_path}')

            el.file_path = dest_appimage_file.get_path()
            el.set_trusted()

            launchers_to_install = extracted_appimage.launchers

            icons_folder = os.path.join(appimages_destination_path, '.icons')

            # Get default exec arguments shipped by this version of the appimage
            term_arguments = extract_terminal_arguments(
                launchers_to_install[0].desktop_entry.getExec())
            exec_arguments = term_arguments['arguments']
            new_default_exec_arguments = ' '.join(exec_arguments)

            # Only preserve the previous exec arguments if the user actually customized them,
            # i.e. they differ from the default that was shipped with the version being replaced.
            # Otherwise, an update that ships a new set of default arguments would always be
            # silently discarded in favor of the old, no-longer-relevant defaults.
            if el.updating_from and el.updating_from.exec_arguments:
                previous_config = Config.get_app_config(el.updating_from)
                previous_default_exec_arguments = previous_config.get('default_exec_arguments', '')

                if el.updating_from.exec_arguments != previous_default_exec_arguments:
                    exec_arguments = shlex.split(el.updating_from.exec_arguments)

            el.exec_arguments = ' '.join(exec_arguments)

            # Move the .desktop files to their default location
            if not os.path.exists(self.user_desktop_files_path):
                os.makedirs(self.user_desktop_files_path)

            new_launchers: List[AppImageLauncher] = []
            used_desktop_filenames: set[str] = set()

            for index, extracted_launcher in enumerate(launchers_to_install):
                if index == 0:
                    launcher_basename = prefixed_filename
                    launcher_exec_arguments = exec_arguments
                else:
                    launcher_basename = f'{prefixed_filename}-{launcher_filename_part(extracted_launcher.desktop_id)}'
                    launcher_exec_arguments = extract_terminal_arguments(
                        extracted_launcher.desktop_entry.getExec())['arguments']

                launcher_basename = launcher_basename.replace(' ', '_')

                desktop_filename = f'{launcher_basename}.desktop'
                suffix = 1

                while desktop_filename in used_desktop_filenames:
                    desktop_filename = f'{launcher_basename}_{suffix}.desktop'
                    suffix += 1

                used_desktop_filenames.add(desktop_filename)
                dest_desktop_file_path = os.path.join(self.user_desktop_files_path, desktop_filename)

                # copy the icon file of this launcher
                dest_appimage_icon_file: Optional[Gio.File] = None

                if extracted_launcher.icon_file and os.path.exists(extracted_launcher.icon_file.get_path()):
                    if not os.path.exists(icons_folder):
                        os.mkdir(icons_folder)

                    _, icon_file_ext = os.path.splitext(extracted_launcher.icon_file.get_path())
                    dest_appimage_icon_file = Gio.File.new_for_path(
                        os.path.join(icons_folder, f'{launcher_basename}{icon_file_ext}')
                    )

                    gio_copy(extracted_launcher.icon_file, dest_appimage_icon_file)

                jd_desktop_entry = JdDesktopEntry.from_file(
                    extracted_launcher.desktop_file.get_path()
                )

                jd_desktop_entry.TryExec = dest_appimage_file.get_path()
                jd_desktop_entry.Exec = shlex.join([dest_appimage_file.get_path(), *launcher_exec_arguments])

                if el.update_logic is AppImageUpdateLogic.KEEP:
                    v_version = self._get_app_version(extracted_appimage, return_hash=True)
                    final_app_name = extracted_launcher.desktop_entry.getName() + f' ({v_version})'
                    jd_desktop_entry.Name.default_text = final_app_name

                desktop_icon = f'applications-other'
                if dest_appimage_icon_file:
                    desktop_icon = f"{dest_appimage_icon_file.get_path()}"

                jd_desktop_entry.Icon = desktop_icon

                for a, action in jd_desktop_entry.Actions.items():
                    a_exec_args = extract_terminal_arguments(action.Exec)
                    action.Icon = desktop_icon
                    action.Exec = shlex.join([dest_appimage_file.get_path(), *a_exec_args['arguments']])

                if version:
                    jd_desktop_entry.CustomKeys['X-AppImage-Version'] = version
                jd_desktop_entry.CustomKeys['X-AppImage-Name'] = extracted_launcher.desktop_entry.getName()

                # finally, write the new .desktop file
                with open(dest_desktop_file_path, 'w+') as desktop_file_python_dest:
                    desktop_file_python_dest.write(jd_desktop_entry.get_text())

                if not os.path.exists(dest_desktop_file_path):
                    raise InternalError('Cannot write the destination .desktop file')

                installed_desktop_entry = DesktopEntry.DesktopEntry(filename=dest_desktop_file_path)

                new_launchers.append(AppImageLauncher(
                    name=installed_desktop_entry.getName(),
                    desktop_file_path=dest_desktop_file_path,
                    desktop_entry=installed_desktop_entry,
                    exec_arguments=' '.join(launcher_exec_arguments),
                    icon_file_path=dest_appimage_icon_file.get_path() if dest_appimage_icon_file else None,
                ))

            self._cleanup_replaced_launchers(el.updating_from, new_launchers)

            el.launchers = new_launchers

            el.desktop_entry = new_launchers[0].desktop_entry
            el.desktop_file_path = new_launchers[0].desktop_file_path
            el.installed_status = InstalledStatus.INSTALLED

            if el.updating_from and el.updating_from.env_variables:
                el.env_variables = el.updating_from.env_variables
                self.update_desktop_file(el)

            has_desktop_integration = False
            for v in el.env_variables:
                if v.startswith('DESKTOPINTEGRATION='):
                    has_desktop_integration = True
                    break

            if not has_desktop_integration:
                el.env_variables.append('DESKTOPINTEGRATION=1')
                self.update_desktop_file(el)

            app_config = Config.get_app_config(el)
            app_config['default_exec_arguments'] = new_default_exec_arguments
            Config.set_app_config(el, app_config)

        except Exception as e:
            logging.error('Appimage installation error: ' + str(e))
            raise e

        if Settings.settings.get_boolean('move-appimage-on-integration'):
            if os.path.dirname(extracted_appimage.appimage_file.get_path()) != appimages_destination_path:
                logging.info('Deleting original appimage file from: '  + extracted_appimage.appimage_file.get_path())
                if not extracted_appimage.appimage_file.delete(None):
                    raise InternalError('Cannot delete original file')

        update_dkt_db = terminal.host_sh(['update-desktop-database', self.user_desktop_files_path, '-q'], return_stderr=True)
        logging.debug(update_dkt_db)

        el.updating_from = None

    def _cleanup_replaced_launchers(self, old_element: Optional[AppImageListElement],
                                    new_launchers: List[AppImageLauncher]):
        """Drop launchers and icons that the version being replaced shipped but the new one does not."""
        if not old_element:
            return

        self._remove_stale_paths(
            self._get_element_desktop_files(old_element),
            {launcher.desktop_file_path for launcher in new_launchers},
            'launcher'
        )
        self._remove_stale_paths(
            self._get_element_icon_files(old_element),
            {launcher.icon_file_path for launcher in new_launchers if launcher.icon_file_path},
            'icon'
        )

    def _remove_stale_paths(self, old_paths: list[str], current_paths: set[str], kind: str):
        for path in old_paths:
            if path in current_paths:
                continue

            try:
                if os.path.exists(path):
                    logging.info(f'Removing obsolete {kind} {path}')
                    os.remove(path)
            except Exception as e:
                logging.warning(f'Cannot remove {path}: {e}')

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

        self.uninstall(el, remove_configuration=False)

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

    def create_list_element_from_file(self, file: Gio.File, return_new_el=False) -> AppImageListElement:
        if not self.can_install_file(file):
            raise InternalError(message='This file type is not supported')

        app_name: str = os.path.basename(file.get_parse_name())
        preview_enabled = False

        file_size = os.stat(file.get_path()).st_size
        el = AppImageListElement(
            name=re.sub(r'\.appimage$', '', app_name, 1, re.IGNORECASE),
            description='',
            version=None,
            provider=self.name,
            installed_status=InstalledStatus.NOT_INSTALLED,
            file_path=file.get_path(),
            size=file_size,
            desktop_entry=None,
            local_file=True,
            trusted=(not preview_enabled)
        )

        el.architecture = self.get_elf_arch(el)

        if return_new_el:
            return el

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
        launchers = list(el.launchers)

        if not launchers and el.desktop_file_path:
            launchers = [AppImageLauncher(
                name=el.name,
                desktop_file_path=el.desktop_file_path,
                desktop_entry=el.desktop_entry,
                exec_arguments=el.exec_arguments,
            )]

        if not launchers:
            raise Exception('desktop_file_path not specified')

        env_vars = ' '.join(el.env_variables)

        if env_vars:
            env_vars = f'env {env_vars} '

        for index, launcher in enumerate(launchers):
            if not launcher.desktop_file_path:
                continue

            jd_desktop_file = JdDesktopEntry.from_file(launcher.desktop_file_path)

            tryexec_command = jd_desktop_file.TryExec
            exec_arguments = el.exec_arguments if index == 0 else launcher.exec_arguments

            if exec_arguments:
                exec_arguments = f' {exec_arguments}'

            exec_command = ''.join([
                env_vars,
                shlex.quote(tryexec_command),
                exec_arguments
            ])

            jd_desktop_file.Exec = exec_command
            jd_desktop_file.write_file(launcher.desktop_file_path)

            launcher.desktop_entry = DesktopEntry.DesktopEntry(filename=launcher.desktop_file_path)

            if index == 0:
                launcher.exec_arguments = el.exec_arguments

        el.desktop_entry = launchers[0].desktop_entry
        el.desktop_file_path = launchers[0].desktop_file_path

    def update_from_url(self, manager, el: AppImageListElement, status_cb: callable) -> AppImageListElement | None:
        try:
            update_file_path, f_hash = manager.download(status_cb)
        except DownloadInterruptedException as de:
            return None
        except Exception as e:
            raise e

        update_gfile = Gio.file_new_for_path(update_file_path)

        if not self.can_install_file(update_gfile):
            raise Exception(_('The downloaded file is not a valid appimage, please check if the provided URL is correct'))

        list_element = self.create_list_element_from_file(update_gfile, return_new_el=True)

        list_element.update_logic = AppImageUpdateLogic.REPLACE
        list_element.updating_from = el
        self.install_file(list_element)

        list_element.updating_from = None
        list_element.update_logic = None

        return list_element

    def is_app_running(self, el: AppImageListElement) -> bool: 
        if not el.file_path:
            return False

        running = terminal.host_sh(["ps", "-eo", "exe"])
        spl = running.split('\n')

        for l in spl:
            l = l.strip()

            if l == el.file_path:
                return True
            
        return False

    # Private methods
    def _run_filepath(self, el: AppImageListElement):
        is_nixos = re.search(r"^NAME=NixOS$", get_osinfo(), re.MULTILINE) is not None

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
        is_nixos = re.search(r"^NAME=NixOS$", get_osinfo(), re.MULTILINE) is not None

        if is_nixos:
            self._nixos_checks()
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

        # We use 7zip to extract the content of the appimage bundle
        # Old versions of Gear Lever used the --appimage-extract command, which is not
        # supported by all the appimage packages

        ###############################################################################

        squashfs_root_folder = os.path.join(dest_path, 'squashfs-root')
        use_appimage_extract = False
        use_7zz = False
        use_unsquashfs = False
        use_dwarf = False
        block_unsafe_extractor = Settings.settings.get_boolean('block-unsafe-extractor')


        try:
            terminal.sandbox_sh(['dwarfsck', f'--input={file.get_path()}', '-q', '-detail=0', '--no-check'], error_quiet=True)
            use_dwarf = True
        except:
            use_7zz = True
            logging.info('Filesystem is not dwarfsck')

        if use_dwarf:
            os.mkdir(squashfs_root_folder)
            logging.info(f'Exctracting with dwarfsextract to {squashfs_root_folder}')

            try:
                terminal.sandbox_sh(['dwarfsextract', f'--input={file.get_path()}', f'--output={squashfs_root_folder}',
                                        '--pattern=**.png','--pattern=**.svg', '--pattern=**.desktop', '--pattern=.DirIcon'])
            except Exception as e:
                logging.error('Extraction with dwarfsextract failed')
                logging.error(str(e))
                use_appimage_extract = True

        if use_7zz:
            try:
                terminal.sandbox_sh(['7zz', 't', file.get_path(), '-y', '-bso0', '-bsp0'])
                z7zoutput = terminal.sandbox_sh(['7zz', 'x', file.get_path(), f'-o{squashfs_root_folder}', '-y', '-bso0', '-bsp0',
                                                    '-ir!*.png', '-ir!*.svg', '-ir!*.desktop',
                                                    '-xr!*.desktop*/', '-xr!*.svg*/', '-xr!*.png*/',
                                                    '-ir0!.DirIcon'
                                                ], cwd=dest_path)
                logging.debug('=== 7zz log ===')
                logging.debug(z7zoutput)
                logging.debug(f'=== end 7zz log ===')
            except Exception as e:

                if glob.glob('*.desktop', root_dir=squashfs_root_folder) and \
                    glob.glob('*.png', root_dir=squashfs_root_folder) or glob.glob('*.svg', root_dir=squashfs_root_folder):
                    logging.warning('Extraction with 7zz failed, but the required files have been extracted')
                else:
                    logging.error('Extraction with 7zz failed')
                    logging.error(str(e))
                    use_unsquashfs = True

        if  use_unsquashfs:
            logging.debug('Testing with unsquashfs')
            appimage_offset = terminal.sandbox_sh(['get_appimage_offset', file.get_path()])

            try:
                terminal.sandbox_sh(['unsquashfs', '-o', appimage_offset, '-l', file.get_path()])
                terminal.sandbox_sh(['unsquashfs', '-o', appimage_offset, '-d', squashfs_root_folder, file.get_path()])
            except Exception as e:
                logging.error('Extraction with unsquashfs failed')
                logging.error(str(e))
                use_appimage_extract = True

        if block_unsafe_extractor and use_appimage_extract:
            raise InternalError(
                _("Any attempts at loading this app's metadata failed; if you want proceed using appimage-extract, please disable the security option in the settings.")
            )

            raise Exception('blocked by security setting')

        if (block_unsafe_extractor == False) and use_appimage_extract:
            logging.info('Extracting with appimage-extract')
            cloned_file = Gio.File.new_for_path(f'{dest_path}/app.appimage')
            gio_copy(file, cloned_file)
            terminal.sandbox_sh(['chmod', '+x', cloned_file.get_path()])
            terminal.sandbox_sh([cloned_file.get_path(), '--appimage-extract'], cwd=dest_path)

        return squashfs_root_folder

    def _load_appimage_metadata(self, el: AppImageListElement) -> ExtractedAppImage:
        if el.extracted:
            return el.extracted

        file = Gio.File.new_for_path(el.file_path)

        launchers: List[ExtractedLauncher] = []

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
                    raise InternalError('Missing mounted extraction folder ' + mounted_appimage_path)

                launchers = self._load_launchers(
                    extraction_folder.get_path(),
                    tmp_folder.get_path(),
                    os.path.basename(el.file_path)
                )

            except Exception as e:
                logging.error(str(e))

        result = ExtractedAppImage()
        result.extraction_folder = tmp_folder.get_path()
        result.appimage_file = file
        result.launchers = launchers
        result.desktop_entry = launchers[0].desktop_entry if launchers else None
        result.icon_file = launchers[0].icon_file if launchers else None
        result.md5 = md5_hash

        el.desktop_entry = result.desktop_entry
        el.extracted = result

        return result

    def _load_launchers(self, extraction_folder_path: str, tmp_folder_path: str,
                        appimage_name: str) -> List[ExtractedLauncher]:
        """Read every visible .desktop file shipped in the root of the AppImage."""
        candidates: List[ExtractedLauncher] = []

        for desktop_name in sorted(os.listdir(extraction_folder_path)):
            if not desktop_name.lower().endswith('.desktop'):
                continue

            gdesk_file = Gio.File.new_for_path(os.path.join(extraction_folder_path, desktop_name))

            if get_giofile_content_type(gdesk_file) != 'application/x-desktop':
                continue

            try:
                desktop_entry = DesktopEntry.DesktopEntry(gdesk_file.get_path())
            except Exception as e:
                logging.warning(f'Cannot parse {desktop_name}: {e}')
                continue

            desktop_id = desktop_id_from_filename(desktop_name)

            candidates.append(ExtractedLauncher(
                desktop_id=desktop_id,
                name=desktop_entry.getName() or desktop_id,
                desktop_file=gdesk_file,
                desktop_entry=desktop_entry,
            ))

        # Launchers hidden from the app menu should not be integrated; if
        # every launcher is hidden, keep one so the app can still be added.
        launchers = [
            launcher for launcher in candidates
            if not launcher.desktop_entry.getNoDisplay() and not launcher.desktop_entry.getHidden()
        ] or candidates[:1]

        if not launchers:
            return []

        primary_index = pick_primary_launcher(
            appimage_name,
            [(launcher.desktop_id, launcher.name) for launcher in launchers]
        )

        launchers.insert(0, launchers.pop(primary_index))

        result: List[ExtractedLauncher] = []

        for index, launcher in enumerate(launchers):
            tmp_desktop_file = Gio.File.new_for_path(
                os.path.join(tmp_folder_path, f'launcher_{index}.desktop')
            )

            try:
                gio_copy(file=launcher.desktop_file, destination=tmp_desktop_file)
                launcher.desktop_entry = DesktopEntry.DesktopEntry(tmp_desktop_file.get_path())
            except Exception as e:
                logging.warning(f'Cannot copy {launcher.desktop_id}: {e}')
                continue

            launcher.desktop_file = tmp_desktop_file

            try:
                launcher.icon_file = self._find_launcher_icon_file(
                    extraction_folder_path,
                    launcher.desktop_entry,
                    allow_dir_icon=(index == 0)
                )
            except Exception as e:
                logging.warning(f'Cannot load the icon of {launcher.desktop_id}: {e}')

            result.append(launcher)

        return result

    def _find_launcher_icon_file(self, extraction_folder_path: str,
                                 desktop_entry: DesktopEntry.DesktopEntry,
                                 allow_dir_icon: bool = False) -> Optional[Gio.File]:
        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#the-filesystem-image
        if not desktop_entry:
            return None

        desktop_entry_icon = desktop_entry.getIcon()

        if not desktop_entry_icon:
            return None

        desktop_entry_icon = re.sub(r"\.(png|svg)$", '', desktop_entry_icon)

        if allow_dir_icon:
            diricon = Gio.File.new_for_path(
                os.path.join(extraction_folder_path, '.DirIcon')
            )

            if diricon.query_exists():
                diricon_ct = get_giofile_content_type(diricon)

                # https://docs.appimage.org/reference/appdir.html
                if diricon_ct in ['image/png', 'image/svg', 'image/svg+xml']:
                    return diricon

                if diricon_ct in ['text/plain']:
                    with open(diricon.get_path(), 'r') as f:
                        possible_icon_path = f.read().strip()

                    icon_candidates = [possible_icon_path]

                    if not os.path.isabs(possible_icon_path):
                        icon_candidates.insert(
                            0, os.path.join(extraction_folder_path, possible_icon_path)
                        )

                    for icon_path in icon_candidates:
                        diricon_linked_to = Gio.File.new_for_path(icon_path)

                        if diricon_linked_to.query_exists() and \
                            get_giofile_content_type(diricon_linked_to) in ['image/png']:
                            return diricon_linked_to

        # icons in the root of the AppDir
        for icon_ext in ['.svg', '.png']:
            icon_candidate = Gio.File.new_for_path(
                os.path.join(extraction_folder_path, f'{desktop_entry_icon}{icon_ext}')
            )

            if icon_candidate.query_exists():
                return icon_candidate

        # icons below usr/share/icons/hicolor;
        # always prefer svg(s) to png(s)
        icons_folder_prefix = '/usr/share/icons/hicolor'
        icon_try_paths = [
            f'{extraction_folder_path}{icons_folder_prefix}/scalable/apps/{desktop_entry_icon}.svg',
            f'{extraction_folder_path}{icons_folder_prefix}/512x512/apps/{desktop_entry_icon}.png',
            f'{extraction_folder_path}{icons_folder_prefix}/256x256/apps/{desktop_entry_icon}.png',
            f'{extraction_folder_path}{icons_folder_prefix}/128x128/apps/{desktop_entry_icon}.png',
            f'{extraction_folder_path}{icons_folder_prefix}/96x96/apps/{desktop_entry_icon}.png',
        ]

        for icon_path in icon_try_paths:
            logging.debug('Looking for icon in: ' + icon_path)
            icon_candidate = Gio.File.new_for_path(icon_path)

            if icon_candidate.query_exists():
                return icon_candidate

        return None

    def _get_appimages_default_destination_path(self) -> str:
        folder = Settings.settings.get_string('appimages-default-folder')
        return re.sub(r'^~', GLib.get_home_dir(), folder)

    def _get_app_version(self, extracted_appimage: Optional[ExtractedAppImage], desktop_entry: Optional[DesktopEntry] = None, return_hash=True):
        if not desktop_entry:
            desktop_entry = extracted_appimage.desktop_entry

        version = desktop_entry.get('X-AppImage-Version', '')

        if (not version) and extracted_appimage and return_hash:
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
