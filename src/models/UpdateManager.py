import logging
import requests
import shutil
import os
import re
import json
from typing import Optional, Callable
from abc import ABC, abstractmethod
from gi.repository import GLib, Gio
from urllib.parse import urlsplit

from ..lib.constants import TMP_DIR
from ..lib import terminal
from ..lib.json_config import read_config_for_app
from ..lib.utils import get_random_string, url_is_valid, get_file_hash
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement
from .Models import DownloadInterruptedException


class UpdateManager(ABC):
    name = ''
    url = ''
    label = ''
    embedded = False
    system_arch = terminal.sandbox_sh(['arch'])
    is_x86 = re.compile(r'(\-|\_|\.)x86(\-|\_|\.)')
    is_arm = re.compile(r'(\-|\_|\.)(arm64|aarch64|armv7l)(\-|\_|\.)')

    @abstractmethod
    def __init__(self, url: str, embedded=False) -> None:
        self.url = url
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

    @staticmethod
    @abstractmethod
    def load_form_rows(update_url: str, embedded: bool) -> list:
        pass

    @staticmethod
    @abstractmethod
    def can_handle_link(url: str) -> bool:
        pass

    @staticmethod
    @abstractmethod
    def get_form_url() -> str:
        pass





# class CodebergUpdater(UpdateManager):
#     staticfile_manager: Optional[StaticFileUpdater]
#     label = 'Codeberg'
#     name = 'CodebergUpdater'

#     def __init__(self, url, **kwargs) -> None:
#         super().__init__(url)
#         self.staticfile_manager = None
#         self.url_data = CodebergUpdater.get_url_data(url)
#         self.url = url

#         self.embedded = False

#     def get_url_data(url: str):
#         # Example: https://codeberg.org/sonusmix/sonusmix/releases/download/v0.1.1/org.sonusmix.Sonusmix-0.1.1.AppImage
#         paths = []
#         if url.startswith('https://'):
#             logging.debug(f'CodebergUpdater: found http url, trying to detect codeberg data')
#             urldata = urlsplit(url)

#             if urldata.netloc != 'codeberg.org':
#                 return False

#             paths = urldata.path.split('/')

#             if len(paths) != 7:
#                 return False

#         return {
#             'username': paths[1],
#             'repo': paths[2],
#             'filename': paths[6],
#         }

#     def can_handle_link(url: str):
#         return CodebergUpdater.get_url_data(url) != False

#     def download(self, status_update_cb) -> str:
#         target_asset = self.fetch_target_asset()
#         if not target_asset:
#             logging.warn('Missing target_asset for Codeberg instance')
#             return

#         dwnl = target_asset['browser_download_url']
#         self.staticfile_manager = StaticFileUpdater(dwnl)
#         fname, etag = self.staticfile_manager.download(status_update_cb)

#         self.staticfile_manager = None
#         return fname, target_asset['id']

#     def cancel_download(self):
#         if self.staticfile_manager:
#             self.staticfile_manager.cancel_download()
#             self.staticfile_manager = None

#     def cleanup(self):
#         if self.staticfile_manager:
#             self.staticfile_manager.cleanup()

#     def convert_glob_to_regex(self, glob_str):
#         """
#         Converts a string with glob patterns to a regular expression.

#         Args:
#             glob_str: A string containing glob patterns.

#         Returns:
#             A regular expression string equivalent to the glob patterns.
#         """
#         regex = ""
#         for char in glob_str:
#             if char == "*":
#                 regex += r".*"
#             else:
#                 regex += re.escape(char)

#         regex = f'^{regex}$'
#         return regex

#     def fetch_target_asset(self):
#         rel_url = f'https://codeberg.org/api/v1/repos/{self.url_data["username"]}/{self.url_data["repo"]}/releases?pre-release=exclude&draft=exclude'

#         try:
#             rel_data_resp = requests.get(rel_url)
#             rel_data_resp.raise_for_status()
#             rel_data = rel_data_resp.json()
#         except Exception as e:
#             logging.error(e)
#             return
        

#         logging.debug(f'Found {len(rel_data)} assets from {rel_url}')
#         if not rel_data:
#             return

#         download_asset = None
#         target_re = re.compile(self.convert_glob_to_regex(self.url_data['filename']))

#         possible_targets = []
#         for asset in rel_data[0]['assets']:
#             if re.match(target_re, asset['name']):
#                 possible_targets.append(asset)

#         if len(possible_targets) == 1:
#             download_asset = possible_targets[0]
#         else:
#             logging.info(f'found {len(possible_targets)} possible file targets')

#             for t in possible_targets:
#                 logging.info(' - ' + t['name'])

#             if self.system_arch == 'x86_64':
#                 for t in possible_targets:
#                     if self.is_x86.search(t['name']) or not self.is_arm.search(t['name']):
#                         download_asset = t
#                         logging.info('found possible target: ' + t['name'])
#                         break

#         if not download_asset:
#             logging.debug(f'No matching assets found from {rel_url}')
#             return

#         logging.debug(f'Found 1 matching asset: {download_asset["browser_download_url"]}')
#         return download_asset

#     def is_update_available(self, el: AppImageListElement):
#         target_asset = self.fetch_target_asset()

#         if target_asset:
#             content_type = requests.head(target_asset['browser_download_url']).headers.get('content-type', None)
#             ct_supported = content_type in [*AppImageProvider.supported_mimes, 'raw',
#                                                     'binary/octet-stream', 'application/octet-stream']

#             if ct_supported:
#                 old_size = os.path.getsize(el.file_path)
#                 is_size_different = target_asset['size'] != old_size
#                 return is_size_different

#         return False



