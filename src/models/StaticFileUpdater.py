import logging
import requests
import shutil
import os
import posixpath
from  urllib.parse import urlparse
import re
from gi.repository import Adw, Gio
from typing import Optional, Literal

from ..lib.utils import terminal
from ..lib.utils import get_random_string, url_is_valid, get_file_hash
from ..lib import json_config
from ..lib.ini_config import Config
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement
from .Models import DownloadInterruptedException
from ..components.AdwEntryRowDefault import AdwEntryRowDefault

from .UpdateManager import UpdateManager

class StaticFileUpdater(UpdateManager):
    label = _('Static URL')
    handles_embedded = 'zsync|'
    name = 'StaticFileUpdater'
    currend_download: Optional[requests.Response]

    @staticmethod
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


    def __init__(self, embedded, el) -> None:
        super().__init__(embedded=embedded, el=el)
        self.form_row = None

    def download(self, status_update_cb) -> tuple[str, str]:
        random_name = get_random_string()
        fname = f'{self.download_folder}/{random_name}.appimage'

        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

        dwnl_url = self.get_config().get('url')
        edwnl_url = self.get_embedded_url()

        if edwnl_url:
            zsync_file = requests.get(edwnl_url).text
            zsync_file_header = zsync_file.split('\n\n', 1)[0]
            sha_pattern = r"URL:\s(.*)"
            match = re.search(sha_pattern, zsync_file_header)

            if match:
                zsyncfile_url = match.group(1)
                urlparsed = urlparse(edwnl_url)
                pp = posixpath.join(posixpath.dirname(urlparsed.path), zsyncfile_url)
                dwnl_url = urlparsed._replace(path=pp,query='',fragment='').geturl()
            else:
                dwnl_url = re.sub(r"\.zsync$", "", edwnl_url)

        if not dwnl_url:
            raise Exception('Missing download URL')

        self.currend_download = requests.get(dwnl_url, stream=True)
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

    def get_embedded_url(self):
        if not self.embedded:
            return None
        
        l = len(self.handles_embedded)
        return self.embedded[l:]

    def is_update_available(self):
        e_url = self.get_embedded_url()
        dwnl_url = self.get_config().get('url')

        if not self.el.file_path:
            return False

        if e_url:
            zsync_file = requests.get(e_url).text
            zsync_file_header = zsync_file.split('\n\n', 1)[0]
            sha_pattern = r"SHA-1:\s*([0-9a-f]{40})"
            curr_version_hash = get_file_hash(Gio.File.new_for_path(self.el.file_path), alg='sha1')

            match = re.search(sha_pattern, zsync_file_header)
            if match:
                return match.group(1) != curr_version_hash
            
        dwnl_url = e_url
        headers = StaticFileUpdater.get_url_headers(dwnl_url)
        resp_cl = int(headers.get('content-length', '0'))
        old_size = os.path.getsize(self.el.file_path)

        logging.debug(f'StaticFileUpdater: new url has length {resp_cl}, old was {old_size}')

        if resp_cl == 0:
            return False

        is_size_different = resp_cl != old_size
        return is_size_different

    def load_form_rows(self):
        url = self.get_config().get('url', '')

        if self.get_embedded_url():
            url = self.get_embedded_url()

        self.form_row = AdwEntryRowDefault(
            text=url,
            icon_name='gl-earth',
            title=_('Update URL'),
            sensitive=(not self.embedded)
        )

        return [self.form_row]

    def get_config_from_form(self):
        url = ''

        if self.form_row:
            url = self.form_row.get_text()

        config = self.get_config()
        config['url'] = url.strip()
        return config

    
    def migrate_v2(self):
        if self.el:
            app_config = json_config.read_config_for_app(self.el)

            if app_config.get('update_url'):
                logging.info('Performing config migration from v1 to v2 for ' + self.el.file_path)
                Config.set_app_config(self.el, {})
                Config.set_app_update_config(self.el, self, {
                    'url':  app_config.get('update_url')
                })