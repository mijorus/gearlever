import logging
import requests
import os
import re
import fnmatch
from typing import Optional, Literal
from gi.repository import Adw, Gio
from urllib.parse import urlsplit

from ..lib.utils import get_file_hash
from ..lib import json_config
from ..lib.ini_config import Config
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

    def __init__(self, el, embedded=False) -> None:
        super().__init__(embedded=embedded, el=el)
        self.staticfile_manager = None
        self.repo_url_row = None
        self.repo_filename_row = None
        self.allow_prereleases_row = None

    def migrate_v2(self):
        app_config = json_config.read_config_for_app(self.el)
        config = None

        if 'update_manager_config' in app_config:
            old_config = app_config.get('update_manager_config', {})
            url_data = urlsplit(old_config.get('repo_url', '')).path.split('/')
            repo = ''

            if len(url_data) > 2:
                repo = '/'.join([url_data[1], url_data[2]])

            config = {
                'allow_prereleases':  old_config.get('allow_prereleases', False),
                'repo': repo,
                'repo_filename': old_config.get('repo_filename', ''),
            }
        elif 'update_url' in app_config:
            url_data = self.get_url_data(app_config['update_url'])

            if url_data:
                config = {
                    'allow_prereleases': False,
                    'repo': '/'.join([url_data['username'], url_data['repo']]),
                    'repo_filename': url_data['filename'],
                }
        
        if config:
            Config.set_app_update_config(self.el, self, config)

    def get_embedded_data(self):
        # Format gh-releases-zsync|probono|AppImages|latest|Subsurface-*x86_64.AppImage.zsync
        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#github-releases
        if not self.embedded:
            return None

        url = self.embedded

        tag_name = '*'
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
    
    def get_url_data(self, url: str):
        # Format gh-releases-zsync|probono|AppImages|latest|Subsurface-*x86_64.AppImage.zsync
        # https://github.com/AppImage/AppImageSpec/blob/master/draft.md#github-releases

        tag_name = '*'
        if url.startswith('https://'):
            logging.debug(f'GithubUpdater: found http url, trying to detect github data')
            urldata = urlsplit(url)

            if urldata.netloc != 'github.com':
                return None

            paths = urldata.path.split('/')

            if len(paths) < 7:
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

    def does_allow_prereleases(self):
        allow_prereleases = False

        if self.embedded:
            embedded_data = self.get_embedded_data()
            if embedded_data:
                allow_prereleases = embedded_data['release'] in ['latest-pre', 'latest-all']
        else:
            allow_prereleases = self.get_config().get('allow_prereleases', False)

        return allow_prereleases

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception(f'Missing target_asset for {self.name} instance')

        dwnl = target_asset['asset']['browser_download_url']
        self.staticfile_manager = StaticFileUpdater(self.el, dwnl)
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
        update_data = None

        if self.embedded:
            update_data = self.get_embedded_data()
        else:
            config = self.get_config()
            repo = config.get('repo', '').split('/')

            if len(repo) < 2:
                return

            update_data = {
                'username': repo[0],
                'repo': repo[1], 
                'filename': config.get('repo_filename'),
            }
        
        if not update_data:
            return
        
        allow_prereleases = self.does_allow_prereleases()

        rel_url = '/'.join([
            'https://api.github.com/repos',
            update_data["username"],
            update_data["repo"],
            'releases',
        ])

        rel_data = []

        if not allow_prereleases:
            rel_url += f'/latest'

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
                if fnmatch.fnmatch(asset['name'], update_data['filename']):
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

    def is_update_available(self):
        if not self.el:
            return False

        target_asset = self.fetch_target_asset()

        if not os.path.exists(self.el.file_path):
            return False

        if target_asset:
            if target_asset['zsync']:
                logging.debug('GithubUpdated: checking zsync file at ' + target_asset['zsync']['browser_download_url'])
                zsync_file = requests.get(target_asset['zsync']['browser_download_url']).text
                zsync_file_header = zsync_file.split('\n\n', 1)[0]
                sha_pattern = r"SHA-1:\s*([0-9a-f]{40})"
                curr_version_hash = get_file_hash(Gio.File.new_for_path(self.el.file_path), alg='sha1')

                match = re.search(sha_pattern, zsync_file_header)
                if match:
                    return match.group(1) != curr_version_hash

            else:
                digest = target_asset['asset'].get('digest', '')
                if digest and digest.startswith('sha256:'):
                    curr_version_hash = get_file_hash(Gio.File.new_for_path(self.el.file_path), alg='sha256')
                    return f'sha256:{curr_version_hash}' != digest

                old_size = os.path.getsize(self.el.file_path)
                is_size_different = target_asset['asset']['size'] != old_size
                return is_size_different

        return False

    def load_form_rows(self): 
        config = self.get_config()
        repo = config.get('repo', '')
        filename = config.get('repo_filename', '')

        if self.embedded:
            url_data = self.get_embedded_data()
            if url_data:
                repo = '/'.join([url_data['username'], url_data['repo']])
                filename = url_data['filename']

        self.repo_url_row = AdwEntryRowDefault(
            icon_name='gl-git',
            sensitive=(not self.embedded),
            title=('Username/Repo')
        )

        self.repo_filename_row = AdwEntryRowDefault(
            icon_name='gl-paper',
            sensitive=(not self.embedded),
            title=_('Release file name')
        )

        if filename:
            self.repo_filename_row.set_text(filename)
        
        if repo:
            self.repo_url_row.set_text(repo)
        
        self.allow_prereleases_row = Adw.SwitchRow(
            title=_('Allow pre-releases'),
            sensitive=(not self.embedded),
            active=self.does_allow_prereleases()
        )

        return [
            self.repo_url_row, 
            self.repo_filename_row,
            self.allow_prereleases_row
        ]

    def get_config_from_form(self):
        allow_prereleases = False
        repo = None
        repo_filename = None

        if self.allow_prereleases_row:
            allow_prereleases = self.allow_prereleases_row.get_active()

        if self.repo_url_row:
            repo = self.repo_url_row.get_text().strip()

        if self.repo_filename_row:
            repo_filename = self.repo_filename_row.get_text()

        return {
            'allow_prereleases': allow_prereleases,
            'repo': repo,
            'repo_filename': repo_filename,
        }

    def validate_config(self, config):
        if len(config.get('repo', '').split('/')) != 2:
            raise Exception(f'Invalid data, please enter <username>/<repo>')