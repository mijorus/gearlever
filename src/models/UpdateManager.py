import logging
import requests
import shutil
import os
from typing import Optional
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
    def download(self) -> str:
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
    def __init__(self, url) -> None:
        super().__init__(url)
        self.url = url

    def can_handle_link(url: str):
        ct = ''

        try:
            resp = requests.head(url, allow_redirects=True)
            ct = resp.headers.get('content-type', '')
        except Exception as e:
            logging.error(e)

        logging.debug(f'{url} responded with content-type: {ct}')
        return ct in [*AppImageProvider.supported_mimes, 'binary/octet-stream']

    def download(self) -> str:
        logging.info(f'Downloading file from {self.url}')

        resp = requests.get(self.url)
        random_name = get_random_string()
        fname = f'{self.download_folder}/{random_name}.appimage'

        os.makedirs(self.download_folder)

        with open(fname, 'wb') as f:
            f.write(resp.content)

        return fname
    
    def cleanup(self):
        shutil.rmtree(self.download_folder)

    def is_update_available(self, el: AppImageListElement):
        resp = requests.head(self.url, allow_redirects=True)
        resp_cl = resp.headers.get('content-length')
        old_size = os.path.getsize(el.file_path)

        logging.debug(f'StaticFileUpdater: new url has length {resp_cl}, old was {old_size}')

        return resp_cl != old_size