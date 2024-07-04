import logging
import requests
import shutil
import os
import re
from typing import Optional, Callable
from abc import ABC, abstractmethod
from gi.repository import GLib
from urllib.parse import urlsplit


from ..lib import terminal
from ..lib.json_config import read_config_for_app
from ..lib.utils import get_random_string, url_is_valid
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement
from .Models import DownloadInterruptedException

class UpdateManager(ABC):
    name = ''

    @abstractmethod
    def __init__(self, url: str, embedded=False) -> None:
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
    def get_models() -> list[UpdateManager]:
        return [StaticFileUpdater, GithubUpdater]

    def check_url(url: str=Optional[str], el: Optional[AppImageListElement]=None,
                    model: Optional[UpdateManager]=None) -> Optional[UpdateManager]:

        models = UpdateManagerChecker.get_models()

        if model:
            models = list(filter(lambda m: m is model, models))

        if el:
            embedded_app_data = UpdateManagerChecker.check_app(el)

            if embedded_app_data:
                for m in models:
                    logging.debug(f'Checking embedded url with {m.__name__}')
                    if m.can_handle_link(embedded_app_data):
                        return m(embedded_app_data, embedded=True)

        if url:
             for m in models:
                logging.debug(f'Checking url with {m.__name__}')
                if m.can_handle_link(url):
                    return m(url)

        return None

    def check_app(el: AppImageListElement) -> Optional[str]:
        # if not terminal.sandbox_sh(['which', 'readelf']):
        #     return

        readelf_out = terminal.sandbox_sh(['readelf', '--string-dump=.upd_info', '--wide', el.file_path])
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
    label = _('Static URL')
    name = 'StaticFileUpdater'
    currend_download: Optional[requests.Response]

    def __init__(self, url, embedded=False) -> None:
        super().__init__(url)
        self.url = re.sub(r"\.zsync$", "", url)
        self.currend_download = None
        self.embedded = embedded

    def can_handle_link(url: str):
        if not url_is_valid(url):
            return False

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
        return is_size_different


class GithubUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Github'
    name = 'GithubUpdater'

    def __init__(self, url, embedded=False) -> None:
        super().__init__(url)
        self.staticfile_manager = None
        self.url_data = GithubUpdater.get_url_data(url)

        self.url = f'https://github.com/{self.url_data["username"]}/{self.url_data["repo"]}'
        self.url += f'/releases/download/{self.url_data["release"]}/{self.url_data["filename"]}'

        self.embedded = embedded

    def get_url_data(url: str):
        # Format gh-releases-zsync|probono|AppImages|latest|Subsurface-*x86_64.AppImage.zsync
        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#github-releases
        if url.startswith('https://'):
            logging.debug(f'GithubUpdater: found http url, trying to detect github data')
            urldata = urlsplit(url)

            if urldata.netloc != 'github.com':
                return False

            paths = urldata.path.split('/')

            if len(paths) != 7:
                return False

            if paths[3] != 'releases' or paths[4] != 'download':
                return False

            rel_name = 'latest'
            if paths[5] == 'continuous':
                rel_name = 'continuous'

            url = f'|{paths[1]}|{paths[2]}|{rel_name}|{paths[6]}'
            logging.debug(f'GithubUpdater: generated appimages-like update string "{url}"')

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
        target_asset = self.fetch_target_asset()
        if not target_asset:
            logging.warn('Missing target_asset for GithubUpdater instance')
            return

        dwnl = target_asset['browser_download_url']
        self.staticfile_manager = StaticFileUpdater(dwnl)
        fname, etag = self.staticfile_manager.download(status_update_cb)

        self.staticfile_manager = None
        return fname, target_asset['id']

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

        regex = f'^{regex}$'
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

        logging.debug(f'Found {len(rel_data["assets"])} assets from {rel_url}')

        zsync_file = None
        target_re = re.compile(self.convert_glob_to_regex(self.url_data['filename']))
        for asset in rel_data['assets']:
            if self.embedded:
                if re.match(target_re, asset['name']) and asset['name'].endswith('.zsync'):
                    zsync_file = asset
                    break
            else:
                if re.match(target_re, asset['name']):
                    zsync_file = asset
                    break

        if not zsync_file:
            logging.debug(f'No matching assets found from {rel_url}')
            return

        target_file = re.sub(r'\.zsync$', '', zsync_file['name'])

        for asset in rel_data['assets']:
            if asset['name'] == target_file:
                logging.debug(f'Found 1 matching asset: {asset["name"]}')
                return asset

    def is_update_available(self, el: AppImageListElement):
        target_asset = self.fetch_target_asset()

        if target_asset:
            ct_supported = target_asset['content_type'] in [*AppImageProvider.supported_mimes,
                                                     'binary/octet-stream', 'application/octet-stream']

            if ct_supported:
                app_conf = read_config_for_app(el)
                old_size = os.path.getsize(el.file_path)
                is_size_different = target_asset['size'] != old_size
                return is_size_different

        return False



