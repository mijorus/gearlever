import os
import platform
import re
import logging
from typing import Optional, Callable, Literal
from abc import ABC, abstractmethod

from ..lib.constants import TMP_DIR
from ..lib.ini_config import Config
from ..providers.AppImageProvider import AppImageListElement


class UpdateManager(ABC):
    name = ''
    label = ''
    handles_embedded: Optional[str] = None
    el: AppImageListElement = None
    system_arch = platform.machine()
    is_x86 = re.compile(r'(\-|\_|\.)x86(\-|\_|\.)')
    is_arm = re.compile(r'(\-|\_|\.)(arm64|aarch64|armv7l)(\-|\_|\.)')

    # Set by a subclass's own fetch_target_asset()/is_update_available()
    # once it has actually located a candidate release, if that manager
    # tracks version numbers at all — StaticFileUpdater/FTPUpdater compare
    # a raw file (hash/size/etag), not a version, so this stays None there.
    _last_available_version: Optional[str] = None

    def __init__(self, el, embedded: Optional[str]=None) -> None:
        self.el = el
        self.download_folder = os.path.join(TMP_DIR, 'downloads')
        self.embedded = embedded

    def cleanup(self):
        pass

    def get_available_version(self) -> Optional[str]:
        """'v1.2.3' -> '1.2.3', but leaves a non-version-looking tag (e.g.
        a plain branch name) untouched. None if this manager has no
        version concept, or hasn't found a candidate release (yet)."""
        version = self._last_available_version
        if version and version[:1] in ('v', 'V') and version[1:2].isdigit():
            return version[1:]
        return version

    @abstractmethod
    def is_update_available(self) -> 'bool | None':
        pass

    @abstractmethod
    def download(self, status_update_cb: Callable[[float], None]) -> tuple[str, str]:
        pass

    @abstractmethod
    def cancel_download(self):
        pass

    @abstractmethod
    def load_form_rows(self) -> list:
        pass

    @abstractmethod
    def get_config_from_form(self) -> dict:
        pass

    def get_config(self):
        return Config.get_app_update_config(self.el)
    
    def validate_config(self, config: dict):
        """Validates the configuration or raises an exception"""
        pass
    
    def migrate_v2(self):
        pass
