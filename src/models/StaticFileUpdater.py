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

from .UpdateManager import UpdateManager

class StaticFileUpdater(UpdateManager):
    label = _('Static URL')
    name = 'StaticFileUpdater'
    currend_download: Optional[requests.Response]

    def __init__(self, url, embedded=False) -> None:
        super().__init__(url)
        self.url = re.sub(r"\.zsync$", "", url)
        self.currend_download = None
        self.embedded = False

        if embedded:
            self.embedded = re.sub(r"\.zsync$", "", url)

    def can_handle_link(url: str):
        if not url_is_valid(url):
            return False

        ct = ''

        if url.endswith('.zsync'):
            # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#zsync-1
            url = re.sub(r"\.zsync$", "", url)

        headers = StaticFileUpdater.get_url_headers(url)
        ct = headers.get('content-type', '')

        logging.debug(f'{url} responded with content-type: {ct}')
        ct_supported = ct in [*AppImageProvider.supported_mimes, 'binary/octet-stream', 'application/octet-stream']

        if not ct_supported:
            logging.warn(f'Provided url "{url}" does not return a valid content-type header')

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

        d_notify_at = 0.1
        with open(fname, 'wb') as f:
            for chunk in self.currend_download.iter_content(block_size):
                f.write(chunk)

                status += block_size

                if total_size:
                    d_perc = (status / total_size)

                    if d_perc > d_notify_at:
                        d_notify_at += 0.1
                        logging.info(f'Download status {d_perc * 100}')
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
        headers = StaticFileUpdater.get_url_headers(self.url)
        resp_cl = int(headers.get('content-length', '0'))
        old_size = os.path.getsize(el.file_path)

        logging.debug(f'StaticFileUpdater: new url has length {resp_cl}, old was {old_size}')

        if resp_cl == 0:
            return False

        is_size_different = resp_cl != old_size
        return is_size_different

    def get_url_headers(url):
        headers = {}
        head_request_error = False

        try:
            resp = requests.head(url, allow_redirects=True)
            resp.raise_for_status()
            headers = resp.headers
        except Exception as e:
            head_request_error = True
            logging.error(str(e))
            
        if head_request_error:
            # If something goes wrong with the Head request, try with stream mode
            logging.warn('Head request failed, trying with stream mode...')

            try:
                resp = requests.get(url, allow_redirects=True, stream=True)
                with resp as r:
                    r.raise_for_status()
                    headers = r.headers
                    r.close()
            except Exception as e:
                logging.error(str(e))
        
        return headers
