import logging
import requests
import os
import re
from fnmatch import fnmatch
from typing import Optional, Literal
from gi.repository import Adw, Gio
from urllib.parse import urlsplit, urljoin

from ..lib import json_config
from ..lib.ini_config import Config
from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault

class ForgejoUpdater(UpdateManager):
    # Example https://git.citron-emu.org/Citron/Emulator

    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Forgejo'
    name = 'ForgejoUpdater'

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.staticfile_manager = None
        self.embedded = False
        self.repo_url_row = None
        self.repo_filename_row = None
        self.allow_prereleases_row = None

    def get_url_data(self, url: str):
        paths = []
        if url.startswith('https://'):
            logging.debug(f'ForgejoUpdater: found http url, trying to detect forgejo data')
            urldata = urlsplit(url)

            paths = urldata.path.split('/')

            if len(paths) < 3:
                return None

            return {
                'netloc': urldata.netloc,
                'username': paths[1],
                'repo': paths[2],
            }
        
        return None

    def migrate_v2(self):
        app_config = json_config.read_config_for_app(self.el)
        config = None

        if 'update_manager_config' in app_config:
            url_data = self.get_url_data(app_config['update_url'])
            urldata = urlsplit(app_config['update_url'])
            paths = urldata.path.split('/')

            if url_data and len(paths) >= 7:
                config = {
                    'allow_prereleases': app_config.get('update_manager_config', {}).get('allow_prereleases', False),
                    'repo_url': '/'.join(['https://', url_data['netloc'], url_data['username'], url_data['repo']]),
                    'repo_filename': paths[6],
                }

        if config:
            Config.set_app_update_config(self.el, self, config)

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception(f'Missing target_asset for {self.name} instance')

        dwnl = target_asset['browser_download_url']
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
        url_data = self.get_url_data(conf['repo_url'])

        if not url_data:
            return

        api_version = 'v1'
        allow_prereleases = conf.get('allow_prereleases', False)

        rel_url = '/'.join([
            f'https://{url_data["netloc"]}',
            'api', 
            api_version,
            'repos',
            url_data["username"],
            url_data["repo"],
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

        if not conf.get('filename'):
            return

        download_asset = None
        possible_targets = []
        for asset in release['assets']:
            if fnmatch(asset['name'], conf.get('filename', '')):
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

    def is_update_available(self):
        target_asset = self.fetch_target_asset()

        if target_asset:
            old_size = os.path.getsize(self.el.file_path)
            is_size_different = target_asset['size'] != old_size
            return is_size_different

        return False

    def load_form_rows(self, embedded=None): 
        config = self.get_config()
        repo_url = config.get('repo_url')
        filename = config.get('repo_filename')

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
            active=config.get('allow_prereleases', False)
        )

        return [
            self.repo_url_row, 
            self.repo_filename_row,
            self.allow_prereleases_row
        ]

    def get_config_from_form(self):
        allow_prereleases = False
        repo_url = None
        repo_filename = None

        if self.allow_prereleases_row:
            allow_prereleases = self.allow_prereleases_row.get_active()

        if self.repo_url_row:
            repo_url = self.repo_url_row.get_text()

        if self.repo_filename_row:
            repo_filename = self.repo_filename_row.get_text()

        return {
            'allow_prereleases': allow_prereleases,
            'repo_url': repo_url,
            'repo_filename': repo_filename,
        }
