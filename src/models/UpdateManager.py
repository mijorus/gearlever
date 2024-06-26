import logging
import requests
import shutil
import os
import re
from typing import Optional, Callable
from abc import ABC, abstractmethod 
from gi.repository import GLib


from ..lib import terminal
from ..lib.json_config import read_config_for_app, save_config_for_app
from ..lib.utils import get_random_string
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement
from .Models import DownloadInterruptedException

class UpdateManager(ABC):
    @abstractmethod
    def __init__(self, url: str) -> None:
        self.download_folder = GLib.get_tmp_dir() + '/it.mijorus.gearlever/downloads'
        pass

    def cleanup(self):
        pass

    @abstractmethod
    def is_update_available(self) -> bool:
        pass

    @abstractmethod
    def download(self, status_update_sb: Callable[[float], None]) -> tuple[str, str]:
        pass
    
    @abstractmethod
    def cancel_download(self):
        pass

    @abstractmethod
    def can_handle_link(url: str) -> bool:
        pass


class UpdateManagerChecker():
    def check_url(url: str, el: Optional[AppImageListElement]=None) -> Optional[UpdateManager]:
        models = [StaticFileUpdater, GithubUpdater]

        if el:
            embedded_app_data = UpdateManagerChecker.check_app(el)

            if embedded_app_data:
                for m in models:
                    logging.debug(f'Checking url with {m.__name__}')
                    if m.can_handle_link(embedded_app_data):
                        return m(embedded_app_data)
                    
        for m in models:
            logging.debug(f'Checking url with {m.__name__}')
            if m.can_handle_link(url):
                return m(url)

        return None

    def check_app(el: AppImageListElement) -> Optional[str]:
        if not terminal.host_sh(['which', 'readelf']):
            return

        readelf_out = terminal.host_sh(['readelf', '--string-dump=.upd_info', '--wide', el.file_path])
        readelf_out = readelf_out.replace('\n', ' ') + ' '

        # Github url
        pattern_gh = r"gh-releases-zsync\|.*(.zsync)"
        matches = re.search(pattern_gh, readelf_out)

        if matches:
            return matches[0].strip()
        
        # Static url
        pattern_link = r"^zsync\|http(.*)\s"
        matches = re.search(pattern_link, readelf_out)

        if matches:
            return re.sub(r"^zsync\|", '', matches[0]).strip()

        return None


class StaticFileUpdater(UpdateManager):
    currend_download: Optional[requests.Response]

    def __init__(self, url) -> None:
        super().__init__(url)
        self.url = re.sub(r"\.zsync$", "", url)
        self.currend_download = None

    def can_handle_link(url: str):
        ct = ''

        if url.endswith('.zsync'):
            # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#zsync-1
            url = re.sub(r"\.zsync$", "", url)

        try:
            resp = requests.head(url, allow_redirects=True)
            ct = resp.headers.get('content-type', '')
        except Exception as e:
            logging.error(e)

        logging.debug(f'{url} responded with content-type: {ct}')
        ct_supported = ct in [*AppImageProvider.supported_mimes, 'binary/octet-stream', 'application/octet-stream']

        return ct_supported

    def download(self, status_update_cb) -> str:
        logging.info(f'Downloading file from {self.url}')

        self.currend_download = requests.get(self.url, stream=True)
        random_name = get_random_string()
        fname = f'{self.download_folder}/{random_name}.appimage'

        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

        etag = self.currend_download.headers.get("etag", '')
        total_size = int(self.currend_download.headers.get("content-length", 0))
        status = 0
        block_size = 1024

        if os.path.exists(fname):
            os.remove(fname)

        with open(fname, 'wb') as f:
            for chunk in self.currend_download.iter_content(block_size):
                f.write(chunk)

                status += block_size
                status_update_cb(status / total_size)

        if os.path.getsize(fname) < total_size:
            raise DownloadInterruptedException()

        self.currend_download = None
        return fname, etag

    def cancel_download(self):
        if self.currend_download:
            self.currend_download.close()
            self.currend_download = None

    def cleanup(self):
        if os.path.exists(self.download_folder):
            shutil.rmtree(self.download_folder)

    def is_update_available(self, el: AppImageListElement):
        resp = requests.head(self.url, allow_redirects=True)
        resp_cl = int(resp.headers.get('content-length'))
        old_size = os.path.getsize(el.file_path)

        logging.debug(f'StaticFileUpdater: new url has length {resp_cl}, old was {old_size}')
        is_size_different = resp_cl != old_size
        is_etag_different = False

        app_conf = read_config_for_app(el)
        etag = resp.headers.get('etag', None)

        if etag and 'last_update_hash' in app_conf:
            is_etag_different = app_conf['last_update_hash'] == etag

        return is_size_different or is_etag_different


class GithubUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]

    def __init__(self, url) -> None:
        super().__init__(url)
        self.url = url
        self.staticfile_manager = None
        self.url_data = GithubUpdater.get_url_data(url)
        self.target_asset = None

    def get_url_data(url):
        # Format gh-releases-zsync|probono|AppImages|latest|Subsurface-*x86_64.AppImage.zsync
        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#github-releases
        items = url.split('|')

        if len(items) != 5:
            return False

        return {
            'username': items[1],
            'repo': items[2],
            'release': items[3],
            'filename': items[4]
        }

    def can_handle_link(url: str):
        return GithubUpdater.get_url_data(url) != False

    def download(self, status_update_cb) -> str:
        if not self.target_asset:
            logging.warn('Missing target_asset for GithubUpdater instance')
            return

        dwnl = self.target_asset['browser_download_url']
        self.staticfile_manager = StaticFileUpdater(dwnl)
        fname, etag = self.staticfile_manager.download(status_update_cb)

        self.staticfile_manager = None
        return fname, self.target_asset['id']

    def cancel_download(self):
        if self.staticfile_manager:
            self.staticfile_manager.cancel_download()
            self.staticfile_manager = None

    def cleanup(self):
        if self.staticfile_manager:
            self.staticfile_manager.cleanup()

    def convert_glob_to_regex(self, glob_str):
        """
        Converts a string with glob patterns to a regular expression.

        Args:
            glob_str: A string containing glob patterns.

        Returns:
            A regular expression string equivalent to the glob patterns.
        """
        regex = ""
        for char in glob_str:
            if char == "*":
                regex += r".*"
            else:
                regex += re.escape(char)

        return regex

    def fetch_target_asset(self):
        rel_url = f'https://api.github.com/repos/{self.url_data["username"]}/{self.url_data["repo"]}'
        rel_url += f'/releases/{self.url_data["release"]}'

        try:
            rel_data_resp = requests.get(rel_url)
            rel_data_resp.raise_for_status()
            rel_data = rel_data_resp.json()
        except Exception as e:
            logging.error(e)
            return
        
        zsync_file = None
        target_re = re.compile(self.convert_glob_to_regex(self.url_data['filename']))
        for asset in rel_data['assets']:
            if re.match(target_re, asset['name']) and asset['name'].endswith('.zsync'):
                zsync_file = asset
                break

        if not zsync_file:
            return

        target_file = re.sub(r'\.zsync$', '', zsync_file['name'])

        for asset in rel_data['assets']:
            if asset['name'] == target_file:
                self.target_asset = asset
                break

    def is_update_available(self, el: AppImageListElement):
        self.fetch_target_asset()

        if self.target_asset:
            ct_supported = self.target_asset['content_type'] in [*AppImageProvider.supported_mimes, 
                                                     'binary/octet-stream', 'application/octet-stream']

            if ct_supported:
                app_conf = read_config_for_app(el)
                old_size = os.path.getsize(el.file_path)
                is_size_different = self.target_asset['size'] != old_size

                if 'last_update_hash' in app_conf:
                    is_id_different = app_conf['last_update_hash'] != self.target_asset['id']
                    return is_id_different
                else:
                    return is_size_different

        return False



