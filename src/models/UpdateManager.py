import os
import platform
import re
from typing import Optional, Callable, Literal
from abc import ABC, abstractmethod

from ..lib.constants import TMP_DIR
from ..lib import terminal
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement


class UpdateManager(ABC):
    name = ''
    url = ''
    label = ''
    handles_embedded: Optional[str] = None
    config = {}
    el: Optional[AppImageListElement] = None
    system_arch = platform.machine()
    is_x86 = re.compile(r'(\-|\_|\.)x86(\-|\_|\.)')
    is_arm = re.compile(r'(\-|\_|\.)(arm64|aarch64|armv7l)(\-|\_|\.)')

    @abstractmethod
    def __init__(self, url: str, embedded: str|Literal[False]=False, el=None) -> None:
        self.el = el
        self.download_folder = os.path.join(TMP_DIR, 'downloads')
        self.embedded = embedded
        self.set_url(url)

    def cleanup(self):
        pass

    @abstractmethod
    def is_update_available(self, el: AppImageListElement) -> bool:
        pass

    @abstractmethod
    def download(self, status_update_cb: Callable[[float], None]) -> tuple[str, str]:
        pass

    @abstractmethod
    def cancel_download(self):
        pass

    @abstractmethod
    def load_form_rows(self, embedded: bool) -> list:
        pass

    @staticmethod
    @abstractmethod
    def can_handle_link(url: str) -> bool:
        pass

    @abstractmethod
    def get_url_from_form(self) -> str:
        pass

    @abstractmethod
    def get_url_from_params(self, **kwargs) -> str:
        pass

    def update_config_from_form(self):
        pass

    @abstractmethod
    def set_url(self, url: str):
        self.url = url

    def get_saved_config(self):
        config = {}

        if self.el:
            config = self.el.get_config().get('update_manager_config', {})

        return config
