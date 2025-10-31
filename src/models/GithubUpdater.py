import logging
import requests
import os
import re
from typing import Optional, Callable
from gi.repository import GLib, Gio
from urllib.parse import urlsplit

from ..lib.utils import get_file_hash
from ..providers.AppImageProvider import AppImageProvider, AppImageListElement
from .Models import DownloadInterruptedException

from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault

class GithubUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'Github'
    name = 'GithubUpdater'
    repo_url_row = None
    repo_filename_row = None

    @staticmethod
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

    @staticmethod
    def can_handle_link(url: str):
        return GithubUpdater.get_url_data(url) != False

    @staticmethod
    def load_form_rows(update_url, embedded=False): 
        url_data = GithubUpdater.get_url_data(update_url)
        repo_url = ''
        filename = ''

        if url_data:
            repo_url = '/'.join(['https://github.com', url_data['username'], url_data['repo']])
            filename = url_data['filename']

        GithubUpdater.repo_url_row = AdwEntryRowDefault(
            text=repo_url,
            icon_name='gl-git',
            sensitive=(not embedded),
            title=_('Repo URL')
        )

        GithubUpdater.repo_filename_row = AdwEntryRowDefault(
            text=filename,
            icon_name='gl-paper',
            sensitive=(not embedded),
            title=_('Release file name')
        )

        return [GithubUpdater.repo_url_row, GithubUpdater.repo_filename_row]

    def __init__(self, url, embedded=False) -> None:
        super().__init__(url)
        self.staticfile_manager = None
        self.url_data = GithubUpdater.get_url_data(url)
        self.url = self.get_url_string_from_data(self.url_data)

        self.embedded = False
        if embedded:
            self.embedded = self.get_url_string_from_data(
                GithubUpdater.get_url_data(embedded)
            )

            self.embedded = re.sub(r"\.zsync$", "", self.embedded)

    def get_url_string_from_data(self, url_data):
        url = f'https://github.com/{url_data["username"]}/{url_data["repo"]}'
        url += f'/releases/download/{url_data["tag_name"]}/{url_data["filename"]}'
        return url

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            logging.warn('Missing target_asset for GithubUpdater instance')
            return '', ''

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
            if self.system_arch == 'x86_64':
                for t in possible_targets:
                    if self.is_x86.search(t['name']) or not self.is_arm.search(t['name']):
                        zsync_file = t
                        logging.info('found possible target: ' + t['name'])
                        break

        if not zsync_file:
            logging.debug(f'No matching assets found from {rel_url}')
            return

        is_zsync = self.embedded and zsync_file['name'].endswith('.zsync')
        target_file = re.sub(r'\.zsync$', '', zsync_file['name'])

        for asset in rel_data['assets']:
            if asset['name'] == target_file:
                logging.debug(f'Found 1 matching asset: {asset["name"]}')

                if is_zsync:
                    return {'asset': asset, 'zsync': zsync_file}

                return {'asset': asset, 'zsync': None}

    def is_update_available(self, el: AppImageListElement):
        target_asset = self.fetch_target_asset()

        if target_asset:
            ct_supported = target_asset['asset']['content_type'] in [*AppImageProvider.supported_mimes, 'raw',
                                                    'binary/octet-stream', 'application/octet-stream']

            if ct_supported:
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
                    old_size = os.path.getsize(el.file_path)
                    is_size_different = target_asset['asset']['size'] != old_size
                    return is_size_different

        return False