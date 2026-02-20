import logging
import requests
import os
import re
from typing import Optional, Literal
from gi.repository import Adw, Gio
from urllib.parse import urlsplit, urljoin

from ..lib.utils import get_file_hash
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement
from .Models import DownloadInterruptedException

from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault

class ForgejoUpdater(UpdateManager):
    # Example https://git.citron-emu.org/Citron/Emulator

    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Forgejo'
    name = 'ForgejoUpdater'

    @staticmethod
    def get_url_data(url: str):
        paths = []
        if url.startswith('https://'):
            logging.debug(f'ForgejoUpdater: found http url, trying to detect forgejo data')
            urldata = urlsplit(url)

            paths = urldata.path.split('/')

            if len(paths) != 7:
                return None

            return {
                'netloc': urldata.netloc,
                'username': paths[1],
                'repo': paths[2],
                'filename': paths[6],
            }
        
        return None
    
    @staticmethod
    def can_handle_link(url: str):
        return ForgejoUpdater.get_url_data(url) != None


    def __init__(self, url, **kwargs) -> None:
        super().__init__(url, **kwargs)
        self.staticfile_manager = None
        self.url_data = ForgejoUpdater.get_url_data(url)
        self.url = url
        self.embedded = False

        self.repo_url_row = None
        self.repo_filename_row = None
        self.allow_prereleases_row = None

    def set_url(self, url: str):
        self.url = url
        self.url_data = self.get_url_data(url)

        self.config = {
            'repo_url': '',
            'repo_filename': '',
            'allow_prereleases': self.get_saved_config().get('allow_prereleases', False)
        }

        if self.url_data:
            self.url = self.get_url_string_from_data(self.url_data)
            self.config['repo_filename'] = self.url_data['filename']
            self.config['repo_url'] = '/'.join([
                'https://' + self.url_data['netloc'],
                self.url_data['username'],
                self.url_data['repo'],
            ])

    def get_url_string_from_data(self, url_data):
        url = f'https://{url_data["netloc"]}/{url_data["username"]}/{url_data["repo"]}'
        url += f'/releases/download/*/{url_data["filename"]}'
        return url

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception(f'Missing target_asset for {self.name} instance')

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
        if not self.url_data:
            return

        api_version = 'v1'
        allow_prereleases = False

        if self.el:
            allow_prereleases = self.el.get_config() \
                .get('update_manager_config', {}) \
                .get('allow_prereleases', False)

        rel_url = '/'.join([
            f'https://{self.url_data["netloc"]}',
            'api', 
            api_version,
            'repos',
            self.url_data["username"],
            self.url_data["repo"],
            'releases'
        ])

        if not allow_prereleases:
            rel_url += '/latest'

        try:
            rel_data_resp = requests.get(rel_url)
            rel_data_resp.raise_for_status()
            rel_data = rel_data_resp.json()
        except Exception as e:
            logging.error(e)
            return

        release = None

        if allow_prereleases:
            for r in rel_data:
                if r['draft'] == False:
                    release = r
                    break
        else:
            release = rel_data

        if not release:
            logging.error('Empty release list')
            return

        logging.debug(f'Found {len(release["assets"])} assets from {rel_url}')

        download_asset = None
        target_re = re.compile(self.convert_glob_to_regex(self.url_data['filename']))

        possible_targets = []
        for asset in release['assets']:
            if re.match(target_re, asset['name']):
                possible_targets.append(asset)

        if len(possible_targets) == 1:
            download_asset = possible_targets[0]
        else:
            logging.info(f'found {len(possible_targets)} possible file targets')

            for t in possible_targets:
                logging.info(' - ' + t['name'])

            if self.system_arch == 'x86_64':
                for t in possible_targets:
                    if self.is_x86.search(t['name']) or not self.is_arm.search(t['name']):
                        download_asset = t
                        logging.info('found possible target: ' + t['name'])
                        break

        if not download_asset:
            logging.debug(f'No matching assets found from {rel_url}')
            return

        logging.debug(f'Found 1 matching asset: {download_asset["browser_download_url"]}')
        return download_asset

    def is_update_available(self, el: AppImageListElement):
        target_asset = self.fetch_target_asset()

        if target_asset:
            old_size = os.path.getsize(el.file_path)
            is_size_different = target_asset['size'] != old_size
            return is_size_different

        return False
    
    def load_form_rows(self, embedded=False): 
        repo_url = self.config.get('repo_url')
        filename = self.config.get('repo_filename')

        self.repo_url_row = AdwEntryRowDefault(
            text=repo_url,
            icon_name='gl-git',
            sensitive=True,
            title=_('Repo URL')
        )

        self.repo_filename_row = AdwEntryRowDefault(
            text=filename,
            icon_name='gl-paper',
            sensitive=True,
            title=_('Release file name')
        )

        self.allow_prereleases_row = Adw.SwitchRow(
            title=_('Allow pre-releases'),
            active=self.config.get('allow_prereleases', False)
        )

        if embedded:
            return [
                self.repo_url_row, 
                self.repo_filename_row,
            ]

        return [
            self.repo_url_row, 
            self.repo_filename_row,
            self.allow_prereleases_row
        ]

    def get_url_from_form(self, **kwargs) -> str:
        if (not self.repo_filename_row) or (not self.repo_url_row):
            return ''

        return '/'.join([
            self.repo_url_row.get_text(),
            'releases/download/*',
            self.repo_filename_row.get_text()
        ])

    def update_config_from_form(self):
        allow_prereleases = False
        repo_url = None
        repo_filename = None

        if self.allow_prereleases_row:
            allow_prereleases = self.allow_prereleases_row.get_active()

        if self.repo_url_row:
            repo_url = self.repo_url_row.get_text()

        if self.repo_filename_row:
            repo_filename = self.repo_filename_row.get_text()

        self.config = {
            'allow_prereleases': allow_prereleases,
            'repo_url': repo_url,
            'repo_filename': repo_filename,
        }

    def get_url_from_params(self, **kwargs):
        return '/'.join([
            kwargs.get('repo_url', ''),
            'releases/download/*',
            kwargs.get('repo_filename', ''),
        ])
