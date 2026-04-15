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

    def __init__(self, el, embedded: Optional[str]=None) -> None:
        self.el = el
        self.download_folder = os.path.join(TMP_DIR, 'downloads')
        self.embedded = embedded

    def cleanup(self):
        pass

    @abstractmethod
    def is_update_available(self) -> bool:
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
    
    def migrate_v2(self):
        pass
