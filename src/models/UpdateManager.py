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
    def check_url(url: str) -> Optional[UpdateManager]:
        models = [StaticFileUpdater, GithubUpdater]

        for m in models:
            logging.debug(f'Checking url with {m.__name__}')
            if m.can_handle_link(url):
                return m(url)

        return None

    def check_app(el: AppImageListElement):
        if not terminal.host_sh(['which', 'readelf']):
            return

        # Github url
        readelf_out = terminal.host_sh(['readelf', '--string-dump=.upd_info', '--wide', el.file_path])
        readelf_out = readelf_out.replace('\n', ' ')
        pattern_gh = r"gh-releases-zsync\|(.*)$"
        pattern_link = r"gh-releases-zsync\|(.*)$"

        matches = re.match(pattern_gh, readelf_out) or \
            re.match(pattern_link, readelf_out)

        if matches:
            return matches[0]



class StaticFileUpdater(UpdateManager):
    currend_download: Optional[requests.Response]

    def __init__(self, url) -> None:
        super().__init__(url)
        self.url = url
        self.currend_download = None

    def can_handle_link(url: str):
        ct = ''

        if url.endswith('.zsync'):
            # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#zsync-1
            url = re.sub(r"\.zsync$", "")

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

        self.currend_download = None
        return fname, etag
    
    def cancel_download(self):
        if self.currend_download:
            self.currend_download.close()
    
    def cleanup(self):
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

        if etag:
            if 'last_update_hash' in app_conf:
                is_etag_different = app_conf['last_update_hash'] == etag

        return is_size_different or is_etag_different


class GithubUpdater(UpdateManager):
    currend_download: Optional[requests.Response]

    def __init__(self, url) -> None:
        super().__init__(url)
        self.url = url
        self.currend_download = None
        self.url_data = GithubUpdater.get_url_data(url)

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

        self.currend_download = None
        return fname, etag
    
    def cancel_download(self):
        if self.currend_download:
            self.currend_download.close()
    
    def cleanup(self):
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

        if etag:
            if 'last_update_hash' in app_conf:
                is_etag_different = app_conf['last_update_hash'] == etag

        return is_size_different or is_etag_different