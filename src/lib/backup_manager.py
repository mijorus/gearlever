import os
import tarfile
import json
import hashlib
import shutil
import logging
from datetime import datetime
from typing import Optional, List, Dict, Callable

from gi.repository import GLib

from .ini_config import Config
from .json_config import read_config_for_app
from ..models.AppListElement import AppListElement


class BackupManager:
    FORMAT_VERSION = "1.0"

    @staticmethod
    def get_dir_size(path: str) -> int:
        """Calculates total size of a directory in bytes without following symlinks."""
        total_size = 0
        if not os.path.exists(path):
            return 0
        if os.path.isfile(path):
            return os.path.getsize(path)
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp) and os.path.exists(fp):
                    total_size += os.path.getsize(fp)
        return total_size

    @staticmethod
    def detect_app_data(el) -> List[Dict]:
        """
        Detects user data and settings locations for an AppImage.
        Checks portable directories (.home / .config next to AppImage)
        and standard XDG directories (~/.config and ~/.local/share).
        """
        data_locations = []
        if not el or not el.file_path:
            return data_locations

        # 1. Check portable directories next to the AppImage
        portable_home = f"{el.file_path}.home"
        if os.path.isdir(portable_home):
            data_locations.append({
                "type": "portable_home",
                "path": portable_home,
                "label": f"Portable Home: {os.path.basename(portable_home)}",
                "size": BackupManager.get_dir_size(portable_home),
                "relative_to": "portable_home",
            })

        portable_config = f"{el.file_path}.config"
        if os.path.isdir(portable_config):
            data_locations.append({
                "type": "portable_config",
                "path": portable_config,
                "label": f"Portable Config: {os.path.basename(portable_config)}",
                "size": BackupManager.get_dir_size(portable_config),
                "relative_to": "portable_config",
            })

        # 2. Check ~/.config for matching folders
        user_config_dir = GLib.get_user_config_dir()
        user_data_dir = GLib.get_user_data_dir()

        candidates = set()
        if el.name:
            candidates.add(el.name.lower())
            candidates.add(el.name.lower().replace(" ", ""))
            candidates.add(el.name.lower().replace(" ", "_"))
            candidates.add(el.name.lower().replace(" ", "-"))

        base_filename = os.path.basename(el.file_path)
        clean_base = base_filename.lower().replace(".appimage", "").replace("gearlever_", "")
        candidates.add(clean_base)
        candidates.add(clean_base.replace("-", "_"))
        candidates.add(clean_base.replace("_", "-"))

        # Exclude common generic system folders to avoid backing up entire dirs
        blacklisted = {
            "", ".", "..", "bin", "lib", "share", "applications", "icons",
            "autostart", "systemd", "pulse", "dconf", "gtk-3.0", "gtk-4.0",
            "menus", "mime", "trash", "gearlever", "it.mijorus.gearlever"
        }

        for candidate in candidates:
            if not candidate or candidate in blacklisted:
                continue

            config_path = os.path.join(user_config_dir, candidate)
            if os.path.isdir(config_path) and os.listdir(config_path):
                # Avoid duplicates
                if not any(d["path"] == config_path for d in data_locations):
                    data_locations.append({
                        "type": "xdg_config",
                        "path": config_path,
                        "label": f"~/.config/{candidate}",
                        "subpath": candidate,
                        "size": BackupManager.get_dir_size(config_path),
                        "relative_to": "xdg_config",
                    })

            # Check ~/.local/share/<candidate>
            local_share_path = os.path.join(user_data_dir, candidate)
            if os.path.isdir(local_share_path) and os.listdir(local_share_path):
                if not any(d["path"] == local_share_path for d in data_locations):
                    data_locations.append({
                        "type": "xdg_data",
                        "path": local_share_path,
                        "label": f"~/.local/share/{candidate}",
                        "subpath": candidate,
                        "size": BackupManager.get_dir_size(local_share_path),
                        "relative_to": "xdg_data",
                    })

        return data_locations

    @staticmethod
    def create_backup(
        selected_apps: List,
        output_file_path: str,
        include_binaries: bool = True,
        include_app_data: bool = True,
        include_gearlever_config: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict:
        """
        Creates a .glbackup (tar.gz) archive containing metadata, configuration,
        and optionally AppImage binaries and application data.
        """
        total_steps = len(selected_apps) + 1
        current_step = 0

        manifest = {
            "format_version": BackupManager.FORMAT_VERSION,
            "created_at": datetime.now().isoformat(),
            "gearlever_version": "4.6.2",
            "include_binaries": include_binaries,
            "include_app_data": include_app_data,
            "include_gearlever_config": include_gearlever_config,
            "apps": []
        }

        # Make sure parent directory of output file exists
        output_dir = os.path.dirname(output_file_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Temporary manifest file
        temp_manifest_path = os.path.join(GLib.get_tmp_dir(), f"manifest_{os.getpid()}.json")

        with tarfile.open(output_file_path, "w:gz") as tar:
            for idx, el in enumerate(selected_apps):
                current_step = idx + 1
                if progress_callback:
                    progress_callback(current_step, total_steps, f"Backing up {el.name}...")

                app_slug = (el.name or "app").lower().replace(" ", "_")
                app_hash = Config.get_app_hash(el) if hasattr(Config, "get_app_hash") else hashlib.md5(el.file_path.encode()).hexdigest()

                app_meta = {
                    "name": el.name,
                    "file_name": os.path.basename(el.file_path),
                    "original_file_path": el.file_path,
                    "description": el.description or "",
                    "exec_arguments": getattr(el, "exec_arguments", ""),
                    "env_variables": getattr(el, "env_variables", []),
                    "version": getattr(el, "version", None),
                    "has_binary": False,
                    "binary_tar_path": None,
                    "binary_size": 0,
                    "desktop_file_name": None,
                    "desktop_tar_path": None,
                    "icon_tar_path": None,
                    "gearlever_config": {},
                    "gearlever_update_config": {},
                    "app_data": []
                }

                # 1. Gear Lever Config & Updates
                if include_gearlever_config:
                    try:
                        app_meta["gearlever_config"] = Config.get_app_config(el)
                    except Exception as e:
                        logging.warning(f"Failed to read app config for {el.name}: {e}")

                    try:
                        app_meta["gearlever_update_config"] = dict(Config.get_app_update_config(el))
                    except Exception as e:
                        logging.warning(f"Failed to read update config for {el.name}: {e}")

                # 2. Desktop file
                desktop_file_path = getattr(el, "desktop_file_path", None)
                if desktop_file_path and os.path.isfile(desktop_file_path):
                    desktop_name = os.path.basename(desktop_file_path)
                    desktop_tar_path = f"desktops/{desktop_name}"
                    tar.add(desktop_file_path, arcname=desktop_tar_path)
                    app_meta["desktop_file_name"] = desktop_name
                    app_meta["desktop_tar_path"] = desktop_tar_path

                # 3. Icon
                icon_path = None
                if hasattr(el, "desktop_entry") and el.desktop_entry:
                    raw_icon = el.desktop_entry.getIcon()
                    if raw_icon and os.path.isfile(raw_icon):
                        icon_path = raw_icon

                # Also check in destination folder .icons
                if not icon_path and el.file_path:
                    dest_icons_dir = os.path.join(os.path.dirname(el.file_path), ".icons")
                    if os.path.isdir(dest_icons_dir):
                        prefixed_name = os.path.splitext(os.path.basename(el.file_path))[0]
                        for f in os.listdir(dest_icons_dir):
                            if f.startswith(prefixed_name):
                                icon_path = os.path.join(dest_icons_dir, f)
                                break

                if icon_path and os.path.isfile(icon_path):
                    icon_ext = os.path.splitext(icon_path)[1]
                    icon_tar_path = f"icons/{app_slug}_{app_hash[:8]}{icon_ext}"
                    tar.add(icon_path, arcname=icon_tar_path)
                    app_meta["icon_tar_path"] = icon_tar_path

                # 4. Binary AppImage
                if include_binaries and el.file_path and os.path.isfile(el.file_path):
                    bin_name = os.path.basename(el.file_path)
                    bin_tar_path = f"apps/{bin_name}"
                    tar.add(el.file_path, arcname=bin_tar_path)
                    app_meta["has_binary"] = True
                    app_meta["binary_tar_path"] = bin_tar_path
                    app_meta["binary_size"] = os.path.getsize(el.file_path)

                # 5. App Data
                if include_app_data:
                    data_locs = BackupManager.detect_app_data(el)
                    for d in data_locs:
                        d_path = d["path"]
                        if os.path.exists(d_path):
                            rel_type = d["relative_to"]
                            if rel_type in ("portable_home", "portable_config"):
                                sub = os.path.basename(d_path)
                            else:
                                sub = d.get("subpath", os.path.basename(d_path))

                            data_tar_path = f"app_data/{app_slug}/{rel_type}/{sub}"
                            tar.add(d_path, arcname=data_tar_path)
                            app_meta["app_data"].append({
                                "relative_to": rel_type,
                                "subpath": sub,
                                "tar_path": data_tar_path,
                                "original_path": d_path,
                                "size": d["size"]
                            })

                manifest["apps"].append(app_meta)

            # Write manifest
            if progress_callback:
                progress_callback(total_steps, total_steps, "Finalizing backup archive...")

            with open(temp_manifest_path, "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2, ensure_ascii=False)

            tar.add(temp_manifest_path, arcname="manifest.json")

        if os.path.exists(temp_manifest_path):
            os.remove(temp_manifest_path)

        return manifest

    @staticmethod
    def inspect_backup(archive_path: str) -> Dict:
        """
        Reads and validates manifest.json from a backup archive without full extraction.
        """
        if not os.path.isfile(archive_path):
            raise FileNotFoundError(f"Backup file not found: {archive_path}")

        with tarfile.open(archive_path, "r:gz") as tar:
            try:
                manifest_member = tar.getmember("manifest.json")
            except KeyError:
                raise ValueError("The selected archive is not a valid Gear Lever backup (missing manifest.json)")

            f = tar.extractfile(manifest_member)
            if not f:
                raise ValueError("Could not read manifest.json from backup archive")

            manifest = json.loads(f.read().decode("utf-8"))
            return manifest

    @staticmethod
    def restore_backup(
        archive_path: str,
        selected_app_names: List[str],
        destination_folder: str,
        restore_app_data: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        desktop_dir: Optional[str] = None,
        config_dir: Optional[str] = None,
        data_dir: Optional[str] = None
    ) -> List[Dict]:
        """
        Restores the selected applications from the backup archive:
        - Extracts AppImage binaries and makes them executable.
        - Restores desktop files and updates Exec/TryExec/Icon paths.
        - Restores icons to destination_folder/.icons.
        - Restores Gear Lever configuration with new hashes.
        - Restores application data (~/.config / portable) if selected.
        """
        manifest = BackupManager.inspect_backup(archive_path)
        apps_to_restore = [a for a in manifest.get("apps", []) if a.get("name") in selected_app_names]

        if not apps_to_restore:
            return []

        if not os.path.exists(destination_folder):
            os.makedirs(destination_folder, exist_ok=True)

        dest_icons_dir = os.path.join(destination_folder, ".icons")
        if not os.path.exists(dest_icons_dir):
            os.makedirs(dest_icons_dir, exist_ok=True)

        user_desktop_dir = desktop_dir or os.path.join(GLib.get_user_data_dir(), "applications")
        try:
            if not os.path.exists(user_desktop_dir):
                os.makedirs(user_desktop_dir, exist_ok=True)
        except Exception as e:
            logging.warning(f"Could not create desktop directory {user_desktop_dir}: {e}")

        user_config_dir = config_dir or GLib.get_user_config_dir()
        user_data_dir = data_dir or GLib.get_user_data_dir()

        total_steps = len(apps_to_restore)
        restored_results = []

        with tarfile.open(archive_path, "r:gz") as tar:
            for idx, app_meta in enumerate(apps_to_restore):
                if progress_callback:
                    progress_callback(idx + 1, total_steps, f"Restoring {app_meta['name']}...")

                app_name = app_meta["name"]
                file_name = app_meta["file_name"]
                new_appimage_path = os.path.join(destination_folder, file_name)

                # 1. Restore AppImage binary
                if app_meta.get("has_binary") and app_meta.get("binary_tar_path"):
                    try:
                        member = tar.getmember(app_meta["binary_tar_path"])
                        with tar.extractfile(member) as src_f, open(new_appimage_path, "wb") as dst_f:
                            shutil.copyfileobj(src_f, dst_f)
                        os.chmod(new_appimage_path, 0o755)
                    except Exception as e:
                        logging.error(f"Error extracting binary for {app_name}: {e}")
                else:
                    # If binary was not included, check if it already exists at original location
                    if not os.path.exists(new_appimage_path):
                        orig = app_meta.get("original_file_path")
                        if orig and os.path.exists(orig):
                            new_appimage_path = orig

                # 2. Restore Icon
                restored_icon_path = None
                if app_meta.get("icon_tar_path"):
                    try:
                        icon_member = tar.getmember(app_meta["icon_tar_path"])
                        icon_ext = os.path.splitext(app_meta["icon_tar_path"])[1]
                        prefixed_filename = os.path.splitext(file_name)[0]
                        target_icon_path = os.path.join(dest_icons_dir, f"{prefixed_filename}{icon_ext}")

                        with tar.extractfile(icon_member) as src_f, open(target_icon_path, "wb") as dst_f:
                            shutil.copyfileobj(src_f, dst_f)
                        restored_icon_path = target_icon_path
                    except Exception as e:
                        logging.warning(f"Error restoring icon for {app_name}: {e}")

                # 3. Restore and adjust Desktop File
                desktop_filename = app_meta.get("desktop_file_name") or f"{os.path.splitext(file_name)[0]}.desktop"
                desktop_target_path = os.path.join(user_desktop_dir, desktop_filename)

                desktop_content = ""
                if app_meta.get("desktop_tar_path"):
                    try:
                        dt_member = tar.getmember(app_meta["desktop_tar_path"])
                        f = tar.extractfile(dt_member)
                        if f:
                            desktop_content = f.read().decode("utf-8")
                    except Exception as e:
                        logging.warning(f"Error reading desktop file from archive for {app_name}: {e}")

                if desktop_content:
                    # Adjust paths in the desktop file
                    lines = []
                    for line in desktop_content.splitlines():
                        if line.startswith("Exec="):
                            # Replace the executable path while preserving arguments
                            parts = line[5:].split(" ", 1)
                            args = parts[1] if len(parts) > 1 else ""
                            line = f"Exec={new_appimage_path}" + (f" {args}" if args else "")
                        elif line.startswith("TryExec="):
                            line = f"TryExec={new_appimage_path}"
                        elif line.startswith("Icon=") and restored_icon_path:
                            line = f"Icon={restored_icon_path}"
                        lines.append(line)

                    try:
                        with open(desktop_target_path, "w", encoding="utf-8") as dt_out:
                            dt_out.write("\n".join(lines) + "\n")
                    except Exception as e:
                        logging.warning(f"Could not write desktop file {desktop_target_path}: {e}")

                # 4. Restore Gear Lever Configuration with new hash
                new_hash = hashlib.md5(new_appimage_path.encode()).hexdigest()
                gl_conf = app_meta.get("gearlever_config", {})
                if gl_conf:
                    gl_conf["name"] = app_name
                    gl_conf["file_path"] = new_appimage_path
                    Config.parser[f"app.{new_hash}"] = gl_conf

                gl_update_conf = app_meta.get("gearlever_update_config", {})
                if gl_update_conf:
                    Config.parser[f"app.{new_hash}.update_manager"] = gl_update_conf

                Config.write()

                # 5. Restore Application Data
                if restore_app_data and app_meta.get("app_data"):
                    for data_entry in app_meta["app_data"]:
                        rel_type = data_entry["relative_to"]
                        subpath = data_entry["subpath"]
                        tar_prefix = data_entry["tar_path"]

                        target_base = None
                        if rel_type == "portable_home":
                            target_base = f"{new_appimage_path}.home"
                        elif rel_type == "portable_config":
                            target_base = f"{new_appimage_path}.config"
                        elif rel_type == "xdg_config":
                            target_base = os.path.join(user_config_dir, subpath)
                        elif rel_type == "xdg_data":
                            target_base = os.path.join(user_data_dir, subpath)

                        if target_base:
                            try:
                                if not os.path.exists(target_base):
                                    os.makedirs(target_base)

                                # Extract all members under tar_prefix into target_base
                                for member in tar.getmembers():
                                    if member.name.startswith(tar_prefix):
                                        rel_inside = os.path.relpath(member.name, tar_prefix)
                                        if rel_inside == ".":
                                            continue
                                        dest_target = os.path.join(target_base, rel_inside)
                                        if member.isdir():
                                            os.makedirs(dest_target, exist_ok=True)
                                        elif member.isfile():
                                            os.makedirs(os.path.dirname(dest_target), exist_ok=True)
                                            with tar.extractfile(member) as src_f, open(dest_target, "wb") as dst_f:
                                                shutil.copyfileobj(src_f, dst_f)
                            except Exception as e:
                                logging.error(f"Error restoring app data for {app_name}: {e}")

                restored_results.append({
                    "name": app_name,
                    "file_path": new_appimage_path,
                    "desktop_file": desktop_target_path
                })

        Config.refresh()
        return restored_results
