import os
import platform
import re
import logging
from typing import Optional, Callable, Literal
from abc import ABC, abstractmethod

from ..lib.constants import TMP_DIR
from ..lib.json_config import save_config_for_app
from ..lib import terminal
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement


class UpdateManager(ABC):
    name = ''
    # url = ''
    label = ''
    handles_embedded: Optional[str] = None
    el: Optional[AppImageListElement] = None
    system_arch = platform.machine()
    is_x86 = re.compile(r'(\-|\_|\.)x86(\-|\_|\.)')
    is_arm = re.compile(r'(\-|\_|\.)(arm64|aarch64|armv7l)(\-|\_|\.)')

    @abstractmethod
    def __init__(self, embedded: Optional[str]=None, el=None) -> None:
        self.el = el
        self.download_folder = os.path.join(TMP_DIR, 'downloads')
        self.embedded = embedded

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
    def load_form_rows(self) -> list:
        pass

    # @staticmethod
    # @abstractmethod
    # def can_handle_link(url: str) -> bool:
    #     pass

    # @abstractmethod
    # def get_url_from_form(self) -> str:
    #     pass

    # @abstractmethod
    # def get_url_from_params(self, **kwargs) -> str:
    #     pass

    @abstractmethod
    def get_config_from_form(self) -> dict:
        pass

    # @abstractmethod
    # def set_url(self, url: str):
    #     self.url = url

    def get_config(self):
        config = {}

        if self.el:
            config = self.el.get_config().get('update_manager_config', {})

        return config
    
    def migrate_v2(self):
        if self.el:
            app_config = self.el.get_config()

            if app_config.get('update_url') and (app_config.get('update_manager_config', None) is None):
                logging.info('Performing config migration from v1 to v2 for ' + self.el.name)
                app_config['update_manager_config'] = self.get_config()
                del app_config['update_url']

                save_config_for_app(app_config)


