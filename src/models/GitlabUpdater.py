import logging
import requests
import os
import re
from fnmatch import fnmatch
from typing import Optional
from urllib.parse import urlsplit, quote, unquote

from ..providers.AppImageProvider import AppImageProvider, AppImageListElement

from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault

# Example:
# https://gitlab.com/librewolf-community/browser/appimage/-/releases

class GitlabUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Gitlab'
    name = 'GitlabUpdater'
    repo_url_row = None
    repo_filename_row = None

    @staticmethod
    def get_url_data(url: str):
        if not url.startswith('https://'):
            return None

        paths = []
        logging.debug(f'GitlabUpdater: found http url, trying to detect gitlab data')
        urldata = urlsplit(url)

        if urldata.netloc != 'gitlab.com':
            return None

        paths = urldata.path.split('/')

        if len(paths) not in [4, 10]:
            return None
        
        if paths[1] == 'api':
            if paths[2] != 'v4' or paths[5] != 'packages':
                return None

            return {
                'project_id': paths[4],
                'filename': paths[9],
                'username': None,
                'repo': None
            }
        else:
            if not urldata.fragment:
                return None

            return {
                'project_id': None,
                'filename': urldata.fragment,
                'username': paths[1],
                'repo': '/'.join(paths[2:4])
            }

    @staticmethod
    def can_handle_link(url: str):
        return GitlabUpdater.get_url_data(url) != None


    def __init__(self, url, **kwargs) -> None:
        super().__init__(url, **kwargs)
        self.staticfile_manager = None
        self.url_data = GitlabUpdater.get_url_data(url)
        self.url = url
        self.embedded = False

        config = {}
        if self.el:
            config = self.el.get_config().get('update_manager_config', {})

        self.config = {
            'repo_url': config.get('repo_url', None),
            'repo_filename': config.get('repo_filename', None),
        }

    def set_url(self, url: str):
        self.url_data = self.get_url_data(url)
        self.url = url

        self.config = {
            'repo_url': '',
            'repo_filename': '',
        }

        if self.url_data:
            repo_url = ''
            if self.url_data['project_id']:
                repo_url = '/'.join(['https://gitlab.com', 'api/v4/projects', self.url_data['project_id']])
            else:
                repo_url = '/'.join(['https://gitlab.com', self.url_data['username'], self.url_data['repo']])

            self.config['repo_url'] = repo_url
            self.config['repo_filename'] = self.url_data['filename']

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception(f'Missing target_asset for {self.name} instance')

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

    def fetch_target_asset(self):
        if not self.url_data:
            return

        project_id = self.url_data['project_id']

        if not project_id:
            project_id = quote(
                self.url_data['username'] + '/' + self.url_data['repo'], 
                safe=''
            )

        rel_url = '/'.join([
            'https://gitlab.com/api/v4/projects',
            project_id,
            'releases'
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
        assets = rel_data[0]['assets']
        for asset in assets['links']:
            link_res_name = asset['url'].split('/')[-1]
            if fnmatch(link_res_name, self.url_data['filename']):
                asset['name'] = link_res_name
                possible_targets.append(asset)

        if len(possible_targets) == 1:
            download_asset = possible_targets[0]
        else:
            logging.info(f'found {len(possible_targets)} possible file targets')
            
            for t in possible_targets:
                logging.info(' - ' + t['name'])

            # Check possible differences with system architecture in file name
            if self.system_arch == 'x86_64':
                for t in possible_targets:
                    if self.is_x86.search(t['name']) or not self.is_arm.search(t['name']):
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
            asset_head_req = requests.head(target_asset['direct_asset_url'])

            is_size_different = False
            old_size = os.path.getsize(el.file_path)
            asset_size = asset_head_req.headers.get('content-length', None)

            if asset_size:
                asset_size = int(asset_size)
                is_size_different = asset_size != old_size

            return is_size_different

        return False
    
    def load_form_rows(self, embedded=False): 
        repo_url = self.config['repo_url']
        filename = self.config['repo_filename']

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
        
        repo_url = self.repo_url_row.get_text()
        filename = self.repo_filename_row.get_text()

        if repo_url.startswith('https://gitlab.com/api'):
            return '/'.join([
                repo_url,
                'packages/generic/<package_name>',
                filename
            ]).strip()
        else:
            return '#'.join([
                repo_url,
                filename
            ]).strip()
        
    def get_url_from_params(self, **kwargs):
        return '#'.join([
            kwargs.get('repo_url', ''),
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