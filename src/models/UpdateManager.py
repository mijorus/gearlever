import os
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
    embedded = False
    system_arch = terminal.sandbox_sh(['arch'])
    is_x86 = re.compile(r'(\-|\_|\.)x86(\-|\_|\.)')
    is_arm = re.compile(r'(\-|\_|\.)(arm64|aarch64|armv7l)(\-|\_|\.)')

    @abstractmethod
    def __init__(self, url: str, embedded: str|Literal[False]=False, config={}) -> None:
        self.url = url
        self.config = config
        self.download_folder = os.path.join(TMP_DIR, 'downloads')

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
    def load_form_rows(self, update_url: str, embedded: bool) -> list:
        pass

    @staticmethod
    @abstractmethod
    def can_handle_link(url: str) -> bool:
        pass

    @abstractmethod
    def get_form_url(self) -> str:
        pass

    def get_form_config(self) -> dict:
        return {}

    @abstractmethod
    def set_url(self, url: str):
        self.url = url