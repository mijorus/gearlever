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
    def can_handle_link(url: str):
        is_embedded = True
        if StaticFileUpdater.handles_embedded and \
            url.startswith(StaticFileUpdater.handles_embedded):
            l = len(StaticFileUpdater.handles_embedded)
            url = url[l:]
            is_embedded = True

        if not url_is_valid(url):
            return False

        ct = ''

        if is_embedded:
            # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#zsync-1
            return True

        headers = StaticFileUpdater.get_url_headers(url)
        ct = headers.get('content-type', '')

        logging.debug(f'{url} responded with content-type: {ct}')
        ct_supported = ct in [*AppImageProvider.supported_mimes, 'binary/octet-stream', 'application/octet-stream']

        if not ct_supported:
            logging.warn(f'Provided url "{url}" does not return a valid content-type header')

        return ct_supported

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


    def __init__(self, url, embedded: str|Literal[False]=False, **kwargs) -> None:
        super().__init__(url, **kwargs)
        self.form_row = None
        self.embedded = embedded
        self.set_url(url)

        logging.info(f'Downloading file from {self.url}')

    def download(self, status_update_cb) -> tuple[str, str]:
        random_name = get_random_string()
        fname = f'{self.download_folder}/{random_name}.appimage'

        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

        dwnl_url = self.url
        if self.embedded and self.url.endswith('.zsync'):
            zsync_file = requests.get(self.url).text
            zsync_file_header = zsync_file.split('\n\n', 1)[0]
            url_pattern = r"URL:\s(.*)"
            match = re.search(url_pattern, zsync_file_header)

            if match:
                zsyncfile_url = match.group(1)

                if zsyncfile_url.startswith('https://') or \
                    zsyncfile_url.startswith('http://'):
                    dwnl_url = zsyncfile_url
                else:
                    urlparsed = urlparse(self.url)
                    pp = posixpath.join(posixpath.dirname(urlparsed.path), zsyncfile_url)
                    dwnl_url = urlparsed._replace(path=pp,query='',fragment='').geturl()
            else:
                dwnl_url = re.sub(r"\.zsync$", "", dwnl_url)

        
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

    def is_update_available(self, el: AppImageListElement):
        if self.embedded:
            zsync_file = requests.get(self.url).text
            zsync_file_header = zsync_file.split('\n\n', 1)[0]
            sha_pattern = r"SHA-1:\s*([0-9a-f]{40})"
            curr_version_hash = get_file_hash(Gio.File.new_for_path(el.file_path), alg='sha1')

            match = re.search(sha_pattern, zsync_file_header)
            if match:
                updatable = match.group(1) != curr_version_hash
                logging.info('SHA-1 detected, app updatable: ' + str(updatable))
                return updatable

        headers = StaticFileUpdater.get_url_headers(self.url)
        resp_cl = int(headers.get('content-length', '0'))
        old_size = os.path.getsize(el.file_path)

        logging.debug(f'StaticFileUpdater: new url has length {resp_cl}, old was {old_size}')

        if resp_cl == 0:
            return False

        is_size_different = resp_cl != old_size
        return is_size_different

    def set_url(self, url: str):
        if self.embedded:
            if StaticFileUpdater.handles_embedded and \
            url.startswith(StaticFileUpdater.handles_embedded):
                l = len(StaticFileUpdater.handles_embedded)
                url = url[l:]

        self.url = url
        self.config = {'url': url}

    def load_form_rows(self, embedded=False):
        self.form_row = AdwEntryRowDefault(
            text=self.config['url'],
            icon_name='gl-earth',
            title=_('Update URL'),
            sensitive=(not embedded)
        )

        return [self.form_row]
    
    def get_url_from_form(self) -> str:
        if (not self.form_row):
            return ''
        
        return self.form_row.get_text().strip()
    
    def get_url_from_params(self, **kwargs):
        return kwargs.get('url', '')
    
    def update_config_from_form(self):
        url = ''

        if self.form_row:
            url = self.form_row.get_text()

        self.config['url'] = url
