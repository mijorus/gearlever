import logging
import requests
import os
import re
from fnmatch import fnmatch
from typing import Optional
from urllib.parse import urlsplit, quote, urlencode

from ..lib import json_config
from ..lib.ini_config import Config
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

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.staticfile_manager = None
        self.embedded = False

    def get_url_data(self, url):
        if not url.startswith('https://'):
            return None

        logging.debug(f'GitlabUpdater: found http url, trying to detect gitlab data')
        urldata = urlsplit(url)

        paths = urldata.path.split('/')

        if len(paths) < 3:
            return None

        return {
            'netloc': urldata.netloc,
            'repo': '/'.join(paths[1:4])
        }

    def migrate_v2(self):
        app_config = json_config.read_config_for_app(self.el)
        config = None

        if 'update_manager_config' in app_config:
            config = app_config.get('update_manager_config', {})
        elif 'update_url' in app_config:
            urldata = urlsplit(app_config['update_url'])
            paths = urldata.path.split('/')

            # Old download URLs have the form:
            # https://gitlab.com/username/repo/-/releases/download/tag/filename
            if urldata.netloc == 'gitlab.com' and len(paths) >= 8:
                config = {
                    'repo_url': f'https://gitlab.com/{paths[1]}/{paths[2]}',
                    'repo_filename': paths[7],
                }

        if config:
            Config.set_app_update_config(self.el, self, config)

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception(f'Missing target_asset for {self.name} instance')

        dwnl = target_asset['direct_asset_url']
        self.staticfile_manager = StaticFileUpdater(self.el, dwnl)
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
        conf = self.get_config()
        url_data = self.get_url_data(conf.get('repo_url', ''))

        if not url_data:
            return

        rel_url = '/'.join([
            ('https://' + url_data['netloc']),
            'api/v4/projects',
            quote(url_data['repo'], safe=''),
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
            if fnmatch(asset['name'], conf['repo_filename']):
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

    def is_update_available(self):
        target_asset = self.fetch_target_asset()

        if target_asset:
            asset_head_req = requests.head(target_asset['direct_asset_url'])

            is_size_different = False
            old_size = os.path.getsize(self.el.file_path)
            asset_size = asset_head_req.headers.get('content-length', None)

            if asset_size:
                asset_size = int(asset_size)
                is_size_different = asset_size != old_size

            return is_size_different

        return False

    def load_form_rows(self, embedded=None):
        config = self.get_config()
        repo_url = config.get('repo_url')
        filename = config.get('repo_filename')

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

    def get_config_from_form(self):
        repo_url = None
        repo_filename = None

        if self.repo_url_row:
            repo_url = self.repo_url_row.get_text()

        if self.repo_filename_row:
            repo_filename = self.repo_filename_row.get_text()

        return {
            'repo_url': repo_url,
            'repo_filename': repo_filename,
        }

    def validate_config(self, config):
        data = self.get_url_data(config['repo_url'])

        if not data:
            raise Exception(f'Invalid {self.name} url')