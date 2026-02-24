import logging
import requests
import os
import re
from fnmatch import fnmatch
from typing import Optional
from urllib.parse import urlsplit, urlencode

from ..providers.AppImageProvider import AppImageProvider, AppImageListElement

from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault

# Example: 
# https://codeberg.org/sonusmix/sonusmix/

class CodebergUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Codeberg'
    name = 'CodebergUpdater'

    @staticmethod
    def get_url_data(url: str):
        paths = []
        if url.startswith('https://'):
            logging.debug(f'CodebergUpdater: found http url, trying to detect codeberg data')
            urldata = urlsplit(url)

            if urldata.netloc != 'codeberg.org':
                return None

            paths = urldata.path.split('/')

            if len(paths) != 7:
                return None

            return {
                'username': paths[1],
                'repo': paths[2],
                'filename': paths[6],
            }
        
        return None

    @staticmethod
    def can_handle_link(url: str):
        return CodebergUpdater.get_url_data(url) != None


    def __init__(self, url, **kwargs) -> None:
        super().__init__(url, **kwargs)
        self.staticfile_manager = None
        self.embedded = False
        self.repo_url_row = None
        self.repo_filename_row = None
        self.set_url(url)

    def set_url(self, url: str):
        self.url = url
        self.url_data = self.get_url_data(url)

        self.config = {
            'repo_url': '',
            'repo_filename': '',
        }

        if self.url_data:
            self.config['repo_url'] =  '/'.join(['https://codeberg.org', self.url_data['username'], self.url_data['repo']])
            self.config['repo_filename'] =  self.url_data['filename']

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

    def fetch_target_asset(self):
        if not self.url_data:
            return

        rel_url = '/'.join([
            f'https://codeberg.org/api/v1/repos', 
            self.url_data["username"],
            self.url_data["repo"],
            'releases?pre-release=exclude&draft=exclude'
        ])

        try:
            rel_data_resp = requests.get(rel_url)
            rel_data_resp.raise_for_status()
            rel_data = rel_data_resp.json()
        except Exception as e:
            logging.error(e)
            return
        

        logging.debug(f'Found {len(rel_data)} assets from {rel_url}')
        if not rel_data:
            return

        download_asset = None

        possible_targets = []
        for asset in rel_data[0]['assets']:
            if fnmatch(asset['name'], self.url_data['filename']):
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
            sensitive=(not embedded),
            title=_('Repo URL')
        )

        self.repo_filename_row = AdwEntryRowDefault(
            text=filename,
            icon_name='gl-paper',
            sensitive=(not embedded),
            title=_('Release file name')
        )

        return [self.repo_url_row, self.repo_filename_row]

    def get_url_from_form(self, ) -> str:
        if (not self.repo_filename_row) or (not self.repo_url_row):
            return ''
        
        return '/'.join([
            self.repo_url_row.get_text(),
            'releases/download/*',
            self.repo_filename_row.get_text()
        ])

    def get_url_from_params(self, **kwargs):
        return '/'.join([
            kwargs.get('repo_url', ''),
            'releases/download/*',
            kwargs.get('repo_filename', ''),
        ])
    
    def update_config_from_form(self):
        repo_url = None
        repo_filename = None

        if self.repo_url_row:
            repo_url = self.repo_url_row.get_text()

        if self.repo_filename_row:
            repo_filename = self.repo_filename_row.get_text()

        self.config = {
            'repo_url': repo_url,
            'repo_filename': repo_filename,
        }



