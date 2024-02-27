
import requests
import shutil
from abc import ABC, abstractmethod 
from gi.repository import GLib

from ..lib.utils import get_random_string
from ..providers.AppImageProvider import AppImageProvider

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
    def check_url(url: str):
        models = [StaticFileUpdater]

        for m in models:
            if m.can_handle_link(url):
                return m(url)
            
        return False


class StaticFileUpdater(UpdateManager):
    def __init__(self, url) -> None:
        super().__init__()
        self.url = url

    def can_handle_link(url: str):
        ct = ''

        try:
            resp = requests.head(url)
            ct = resp.headers.get('Content-Type', '')        
        except Exception as e:
            pass

        return ct in AppImageProvider.supported_mimes

    def download(self):
        resp = requests.get(self.url)
        random_name = get_random_string()
        fname = f'{self.download_folder}/{random_name}.appimage'

        with open(fname, 'wb') as f:
            f.write(resp.content)

        return fname
    
    def cleanup(self):
        shutil.rmtree(self.download_folder)