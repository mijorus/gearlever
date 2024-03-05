import logging
import requests
import shutil
import os
from typing import Optional, Callable
from abc import ABC, abstractmethod 
from gi.repository import GLib

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
    def download(self, status_update_sb: Callable[[float], None]) -> str:
        pass
    
    @abstractmethod
    def cancel_download(self):
        pass

    @abstractmethod
    def can_handle_link(url: str) -> bool:
        pass


class UpdateManagerChecker():
    def check_url(url: str) -> Optional[UpdateManager]:
        models = [StaticFileUpdater]

        for m in models:
            if m.can_handle_link(url):
                return m(url)
            
        return None


class StaticFileUpdater(UpdateManager):
    currend_download: Optional[requests.Response]

    def __init__(self, url) -> None:
        super().__init__(url)
        self.url = url
        self.currend_download = None

    def can_handle_link(url: str):
        ct = ''

        try:
            resp = requests.head(url, allow_redirects=True)
            ct = resp.headers.get('content-type', '')
        except Exception as e:
            logging.error(e)

        logging.debug(f'{url} responded with content-type: {ct}')
        return ct in [*AppImageProvider.supported_mimes, 'binary/octet-stream']

    def download(self, status_update_cb) -> str:
        logging.info(f'Downloading file from {self.url}')

        self.currend_download = requests.get(self.url, stream=True)
        random_name = get_random_string()
        fname = f'{self.download_folder}/{random_name}.appimage'

        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

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
        return fname
    
    def cancel_download(self):
        if self.currend_download:
            self.currend_download.close()
    
    def cleanup(self):
        shutil.rmtree(self.download_folder)

    def is_update_available(self, el: AppImageListElement):
        resp = requests.head(self.url, allow_redirects=True)
        resp_cl = resp.headers.get('content-length')
        old_size = os.path.getsize(el.file_path)

        logging.debug(f'StaticFileUpdater: new url has length {resp_cl}, old was {old_size}')

        return resp_cl != old_size