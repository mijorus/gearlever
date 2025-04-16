import logging
import requests
import shutil
import os
import re
import json
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

    def get_model_by_name(manager_label: str) -> Optional[UpdateManager]:
        item = list(filter(lambda m: m.name == manager_label, 
                                    UpdateManagerChecker.get_models()))

        if item:
            return item[0]

        return None

    def check_url_for_app(el: AppImageListElement=None):
        app_conf = read_config_for_app(el)
        update_url = app_conf.get('update_url', None)
        update_url_manager = app_conf.get('update_url_manager', None)
        return UpdateManagerChecker.check_url(update_url, el, 
            model=UpdateManagerChecker.get_model_by_name(update_url_manager))

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

class GithubUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Github'
    name = 'GithubUpdater'

    def __init__(self, url, embedded=False) -> None:
        super().__init__(url)
        self.staticfile_manager = None
        self.url_data = GithubUpdater.get_url_data(url)

        self.url = f'https://github.com/{self.url_data["username"]}/{self.url_data["repo"]}'
        self.url += f'/releases/download/{self.url_data["tag_name"]}/{self.url_data["filename"]}'

        self.embedded = embedded

    def get_url_data(url: str):
        # Format gh-releases-zsync|probono|AppImages|latest|Subsurface-*x86_64.AppImage.zsync
        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#github-releases

        tag_name = '*'
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
            tag_name = paths[5]

            url = f'|{paths[1]}|{paths[2]}|{rel_name}|{paths[6]}'
            logging.debug(f'GithubUpdater: generated appimages-like update string "{url}"')

        items = url.split('|')

        if len(items) != 5:
            return False

        return {
            'username': items[1],
            'repo': items[2],
            'release': items[3],
            'filename': items[4],
            'tag_name': tag_name
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
            if 'rate limit exceeded' in str(e):
                print(str(e))

            logging.error(e)
            return

        logging.debug(f'Found {len(rel_data["assets"])} assets from {rel_url}')

        zsync_file = None
        target_re = re.compile(self.convert_glob_to_regex(self.url_data['filename']))
        target_tag = re.compile(self.convert_glob_to_regex(self.url_data['tag_name']))

        if not re.match(target_tag, rel_data['tag_name']):
            logging.debug(f'Release tag names do not match: {rel_data["tag_name"]} != {self.url_data["tag_name"]}')
            return

        possible_targets = []
        for asset in rel_data['assets']:
            if self.embedded:
                if re.match(target_re, asset['name']) and asset['name'].endswith('.zsync'):
                    possible_targets = [asset]
                    break
            else:
                if re.match(target_re, asset['name']):
                    possible_targets.append(asset)

        if len(possible_targets) == 1:
            zsync_file = possible_targets[0]
        else:
            logging.info(f'found {len(possible_targets)} possible file targets')
            
            for t in possible_targets:
                logging.info(' - ' + t['name'])

            # Check possible differences with system architecture in file name
            system_arch = terminal.sandbox_sh(['arch'])
            is_x86 = re.compile(r'(\-|\_|\.)x86(\-|\_|\.)')
            is_arm = re.compile(r'(\-|\_|\.)(arm64|aarch64|armv7l)(\-|\_|\.)')

            if system_arch == 'x86_64':
                for t in possible_targets:
                    if is_x86.search(t['name']) or not is_arm.search(t['name']):
                        zsync_file = t
                        logging.info('found possible target: ' + t['name'])
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
            ct_supported = target_asset['content_type'] in [*AppImageProvider.supported_mimes, 'raw',
                                                    'binary/octet-stream', 'application/octet-stream']

            if ct_supported:
                old_size = os.path.getsize(el.file_path)
                is_size_different = target_asset['size'] != old_size
                return is_size_different

        return False

class GitlabUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Gitlab'
    name = 'GitlabUpdater'

    def __init__(self, url) -> None:
        super().__init__(url)
        self.staticfile_manager = None
        self.url_data = GitlabUpdater.get_url_data(url)
        self.url = url

        self.embedded = False

    def get_url_data(url: str):
        paths = []
        if url.startswith('https://'):
            logging.debug(f'GitlabUpdater: found http url, trying to detect github data')
            urldata = urlsplit(url)

            if urldata.netloc != 'gitlab.com':
                return False

            paths = urldata.path.split('/')

            if len(paths) != 10:
                return False

            if paths[1] != 'api' or paths[2] != 'v4' or paths[5] != 'packages':
                return False

        return {
            'username': paths[1],
            'filename': paths[9],
        }

    def can_handle_link(url: str):
        return GithubUpdater.get_url_data(url) != False

    def download(self, status_update_cb) -> str:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            logging.warn('Missing target_asset for GithubUpdater instance')
            return

        dwnl = target_asset['direct_asset_url']
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
        rel_url = f'https://gitlab.com/api/v4/projects/{self.url_data["username"]}/releases'

        try:
            rel_data_resp = requests.get(rel_url)
            rel_data_resp.raise_for_status()
            rel_data = rel_data_resp.json()
        except Exception as e:
            logging.error(e)
            return

        logging.debug(f'Found {len(rel_data)} assets from {rel_url}')

        download_asset = None
        target_re = re.compile(self.convert_glob_to_regex(self.url_data['filename']))

        possible_targets = []
        for asset in rel_data:
            for link_data in asset['links']:
                link_res_name = link_data['url'].split('/')[-1]
                if re.match(target_re, link_res_name):
                    asset['name'] = link_res_name
                    possible_targets.append(asset)

        if len(possible_targets) == 1:
            download_asset = possible_targets[0]
        else:
            logging.info(f'found {len(possible_targets)} possible file targets')
            
            for t in possible_targets:
                logging.info(' - ' + t['name'])

            # Check possible differences with system architecture in file name
            system_arch = terminal.sandbox_sh(['arch'])
            is_x86 = re.compile(r'(\-|\_|\.)x86(\-|\_|\.)')
            is_arm = re.compile(r'(\-|\_|\.)(arm64|aarch64|armv7l)(\-|\_|\.)')

            if system_arch == 'x86_64':
                for t in possible_targets:
                    if is_x86.search(t['name']) or not is_arm.search(t['name']):
                        download_asset = t
                        logging.info('found possible target: ' + t['name'])
                        break

        if not download_asset:
            logging.debug(f'No matching assets found from {rel_url}')
            return

        logging.debug(f'Found 1 matching asset: {download_asset["direct_asset_url"]}')
        return download_asset

    def is_update_available(self, el: AppImageListElement):
        target_asset = self.fetch_target_asset()

        if target_asset:
            content_type = requests.head(target_asset['direct_asset_url']).headers.get('content-type', None)
            ct_supported = content_type in [*AppImageProvider.supported_mimes, 'raw',
                                                    'binary/octet-stream', 'application/octet-stream']

            if ct_supported:
                old_size = os.path.getsize(el.file_path)
                is_size_different = target_asset['size'] != old_size
                return is_size_different

        return False



