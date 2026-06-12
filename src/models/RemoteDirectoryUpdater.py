import logging
import requests
import os
import re
from typing import Optional
from urllib.parse import urljoin, urlsplit, unquote

from ..lib import json_config
from ..lib.ini_config import Config
from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault


# Lists a plain HTTP/HTTPS directory index (e.g. Apache/nginx autoindex) and
# picks the most recent version of a file matching a wildcard pattern.
#
# Example:
# url:      https://download.linphone.org/releases/linux/app/
# filename: Linphone-*.AppImage
#
# The "*" represents the version part of the file name; every matching file is
# listed and the highest version is selected for the update.

class RemoteDirectoryUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = _('Web directory')
    name = 'RemoteDirectoryUpdater'

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.staticfile_manager = None
        self.embedded = False

        self.url_row = None
        self.filename_row = None

    @staticmethod
    def _natural_sort_key(value: str):
        """Splits a string into text/number chunks so that versions sort
        naturally (e.g. 5.0.10 is greater than 5.0.9)."""
        key = []
        for part in re.split(r'(\d+)', value):
            if part.isdigit():
                key.append((1, int(part), ''))
            elif part:
                key.append((0, 0, part))

        return tuple(key)

    @staticmethod
    def _pattern_to_regex(pattern: str) -> re.Pattern:
        """Turns a wildcard pattern (``*`` and ``?``) into an anchored regex
        where every ``*`` becomes a capturing group (the version part)."""
        regex = ''
        for char in pattern:
            if char == '*':
                regex += '(.+?)'
            elif char == '?':
                regex += '.'
            else:
                regex += re.escape(char)

        return re.compile(f'^{regex}$')

    def _list_remote_files(self, url: str) -> list[str]:
        """Returns the file names listed in an HTML directory index."""
        resp = requests.get(url)
        resp.raise_for_status()

        files = []
        for match in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', resp.text, re.IGNORECASE):
            href = match.group(1)

            # Skip query-only links (sorting links like "?C=N;O=D")
            if href.startswith('?') or href.startswith('#'):
                continue

            # Keep only entries that live in the current directory: a bare file
            # name without any path separator (drop parent dirs and subfolders).
            path = urlsplit(href).path
            if not path or path.endswith('/'):
                continue

            name = unquote(path.rstrip('/').split('/')[-1])
            if name in ('', '.', '..'):
                continue

            files.append(name)

        return files

    def fetch_target_asset(self):
        conf = self.get_config()
        url = conf.get('url', '')
        pattern = conf.get('filename', '')

        if not url or not pattern:
            return

        if not url.endswith('/'):
            url += '/'

        try:
            files = self._list_remote_files(url)
        except Exception as e:
            logging.error(e)
            return

        logging.debug(f'Found {len(files)} entries from {url}')

        regex = self._pattern_to_regex(pattern)

        possible_targets = []
        for name in files:
            match = regex.fullmatch(name)
            if not match:
                continue

            # The version is what the wildcard(s) captured
            version_parts = match.groups() or (name,)
            version = '-'.join(version_parts)
            sort_key = tuple(self._natural_sort_key(p) for p in version_parts)

            possible_targets.append({
                'name': name,
                'version': version,
                'sort_key': sort_key,
                'browser_download_url': urljoin(url, name),
            })

        if not possible_targets:
            logging.debug(f'No matching files found from {url}')
            return

        # The highest version wins
        download_asset = max(possible_targets, key=lambda t: t['sort_key'])

        logging.debug(f'Found latest matching asset: {download_asset["browser_download_url"]}'
                      f' (version {download_asset["version"]})')

        return download_asset

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception(f'Missing target_asset for {self.name} instance')

        dwnl = target_asset['browser_download_url']
        self.staticfile_manager = StaticFileUpdater(self.el, dwnl)
        fname, etag = self.staticfile_manager.download(status_update_cb)

        self.staticfile_manager = None
        return fname, target_asset['version']

    def cancel_download(self):
        if self.staticfile_manager:
            self.staticfile_manager.cancel_download()
            self.staticfile_manager = None

    def cleanup(self):
        if self.staticfile_manager:
            self.staticfile_manager.cleanup()

    def is_update_available(self):
        config = self.get_config()
        target_asset = self.fetch_target_asset()

        if not self.el.file_path or not os.path.exists(self.el.file_path):
            return False

        if target_asset:
            headers = StaticFileUpdater.get_url_headers(target_asset['browser_download_url'])
            asset_size = int(headers.get('content-length', '0'))
            old_size = os.path.getsize(self.el.file_path)

            logging.debug(f'RemoteDirectoryUpdater: new file has length {asset_size}, old was {old_size}')

            if asset_size == 0:
                return None

            return asset_size != old_size

        if config.get('filename'):
            return None

        return False

    def load_form_rows(self, embedded=None):
        config = self.get_config()
        url = config.get('url')
        filename = config.get('filename')

        self.url_row = AdwEntryRowDefault(
            text=url,
            icon_name='gl-earth',
            sensitive=(not embedded),
            title=_('Directory URL')
        )

        self.filename_row = AdwEntryRowDefault(
            text=filename,
            icon_name='gl-paper',
            sensitive=(not embedded),
            title=_('File name pattern')
        )

        return [self.url_row, self.filename_row]

    def get_config_from_form(self):
        url = None
        filename = None

        if self.url_row:
            url = self.url_row.get_text().strip()

        if self.filename_row:
            filename = self.filename_row.get_text().strip()

        return {
            'url': url,
            'filename': filename,
        }

    def validate_config(self, config):
        url = config.get('url', '')
        filename = config.get('filename', '')

        if (not url.startswith('http://')) and (not url.startswith('https://')):
            raise Exception('Enter a valid HTTP url')

        if '*' not in filename:
            raise Exception('The file name must contain a "*" wildcard for the version')
