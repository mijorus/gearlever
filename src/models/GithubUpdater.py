import logging
import requests
import os
import re
import fnmatch
from typing import Optional, Literal
from gi.repository import Adw, Gio
from urllib.parse import urlsplit

from ..lib.utils import get_file_hash
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement
from .Models import DownloadInterruptedException

from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault

class GithubUpdater(UpdateManager):
    handles_embedded = 'gh-releases-zsync|'
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Github'
    name = 'GithubUpdater'

    @staticmethod
    def get_url_data(url: str):
        # Format gh-releases-zsync|probono|AppImages|latest|Subsurface-*x86_64.AppImage.zsync
        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#github-releases

        tag_name = '*'
        if url.startswith('https://'):
            logging.debug(f'GithubUpdater: found http url, trying to detect github data')
            urldata = urlsplit(url)

            if urldata.netloc != 'github.com':
                return None

            paths = urldata.path.split('/')

            if len(paths) != 7:
                return None

            if paths[3] != 'releases' or paths[4] != 'download':
                return None

            rel_name = 'latest'
            tag_name = paths[5]

            url = f'|{paths[1]}|{paths[2]}|{rel_name}|{paths[6]}'
            logging.debug(f'GithubUpdater: generated appimages-like update string "{url}"')

        items = url.split('|')

        if len(items) != 5:
            return None

        return {
            'username': items[1],
            'repo': items[2],
            'release': items[3],
            'filename': items[4],
            'tag_name': tag_name
        }

    @staticmethod
    def can_handle_link(url: str):
        return GithubUpdater.get_url_data(url) != None

    def __init__(self, url, embedded: str|Literal[False]=False, **kwargs) -> None:
        super().__init__(url, embedded, **kwargs)
        self.staticfile_manager = None
        self.repo_url_row = None
        self.repo_filename_row = None
        self.allow_prereleases_row = None
        self.embedded = embedded

        self.set_url(url)

    def does_allow_prereleases(self):
        allow_prereleases = False

        if self.embedded:
            if self.url_data:
                allow_prereleases = self.url_data['release'] in ['latest-pre', 'latest-all']
        else:
            allow_prereleases = self.get_saved_config().get('allow_prereleases', False)

        return allow_prereleases

    def set_url(self, url: str):
        self.url = url
        self.url_data = self.get_url_data(url)

        self.config = {
            'repo_url': '',
            'repo_filename': '',
            'allow_prereleases': self.does_allow_prereleases()
        }

        if self.url_data:
            self.url = self.get_url_string_from_data(self.url_data)
            self.config['repo_url'] =  '/'.join(['https://github.com', self.url_data['username'], self.url_data['repo']])
            self.config['repo_filename'] =  self.url_data['filename']

    def get_url_string_from_data(self, url_data):
        url = f'https://github.com/{url_data["username"]}/{url_data["repo"]}'
        url += f'/releases/download/{url_data["tag_name"]}/{url_data["filename"]}'
        return url

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception(f'Missing target_asset for {self.name} instance')

        dwnl = target_asset['asset']['browser_download_url']
        self.staticfile_manager = StaticFileUpdater(dwnl)
        fname, etag = self.staticfile_manager.download(status_update_cb)

        self.staticfile_manager = None
        return fname, target_asset['asset']['id']

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
        
        allow_prereleases = self.does_allow_prereleases()

        release_name = self.url_data["release"]

        rel_url = '/'.join([
            'https://api.github.com/repos',
            self.url_data["username"],
            self.url_data["repo"],
            'releases',
        ])

        rel_data = []

        if not allow_prereleases:
            rel_url += f'/{release_name}'

        try:
            rel_data_resp = requests.get(rel_url)
            rel_data_resp.raise_for_status()
            rel_data = rel_data_resp.json()
            if not allow_prereleases:
                rel_data = [rel_data]
        except Exception as e:
            if 'rate limit exceeded' in str(e):
                print(str(e))

            logging.error(e)
            return

        release = None

        possible_targets = []
        tmp_target_file = None

        for release in rel_data:
            found = False

            if not allow_prereleases and release['draft']:
                continue

            for asset in release['assets']:
                if fnmatch.fnmatch(asset['name'], self.url_data['filename']):
                    found = True
                    possible_targets.append(asset)
                    if self.embedded:
                        break

            if found:
                break

        if not release:
            return

        if len(possible_targets) == 1:
            tmp_target_file = possible_targets[0]
        else:
            logging.info(f'found {len(possible_targets)} possible file targets')
            
            for t in possible_targets:
                logging.info(' - ' + t['name'])

            # Check possible differences with system architecture in file name
            if self.system_arch == 'x86_64':
                for t in possible_targets:
                    if self.is_x86.search(t['name']) or not self.is_arm.search(t['name']):
                        tmp_target_file = t
                        logging.info('found possible target: ' + t['name'])
                        break

        if not tmp_target_file:
            logging.debug(f'No matching assets found from {rel_url}')
            return

        is_zsync = self.embedded and tmp_target_file['name'].endswith('.zsync')
        target_file = re.sub(r'\.zsync$', '', tmp_target_file['name'])

        for asset in release['assets']:
            if asset['name'] == target_file:
                logging.debug(f'Found 1 matching asset: {asset["name"]}')

                if is_zsync:
                    return {'asset': asset, 'zsync': tmp_target_file}

                return {'asset': asset, 'zsync': None}

    def is_update_available(self, el: AppImageListElement):
        target_asset = self.fetch_target_asset()

        if not os.path.exists(el.file_path):
            return False

        if target_asset:
            if target_asset['zsync']:
                logging.debug('GithubUpdated: checking zsync file at ' + target_asset['zsync']['browser_download_url'])
                zsync_file = requests.get(target_asset['zsync']['browser_download_url']).text
                zsync_file_header = zsync_file.split('\n\n', 1)[0]
                sha_pattern = r"SHA-1:\s*([0-9a-f]{40})"
                curr_version_hash = get_file_hash(Gio.File.new_for_path(el.file_path), alg='sha1')

                match = re.search(sha_pattern, zsync_file_header)
                if match:
                    return match.group(1) != curr_version_hash

            else:
                digest = target_asset['asset'].get('digest', '')
                if digest and digest.startswith('sha256:'):
                    curr_version_hash = get_file_hash(Gio.File.new_for_path(el.file_path), alg='sha256')
                    return f'sha256:{curr_version_hash}' != digest

                old_size = os.path.getsize(el.file_path)
                is_size_different = target_asset['asset']['size'] != old_size
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
        
        self.allow_prereleases_row = Adw.SwitchRow(
            title=_('Allow pre-releases'),
            sensitive=(not embedded),
            active=self.does_allow_prereleases()
        )

        if embedded:
            return [
                self.repo_url_row, 
                self.repo_filename_row,
                self.allow_prereleases_row
            ]

        return [
            self.repo_url_row, 
            self.repo_filename_row,
            self.allow_prereleases_row
        ]

    def get_url_from_form(self) -> str:
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
