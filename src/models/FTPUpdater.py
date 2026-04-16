import logging
import os
import ftputil
from ftputil.file import FTPFile
from ftputil import FTPHost
import fnmatch
import shutil
from typing import Optional
from urllib.parse import urlsplit
from ..lib.utils import get_random_string, get_file_hash
from ..lib import json_config
from ..lib.ini_config import Config

from .Models import DownloadInterruptedException
from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault


# Example:
# https://download.kde.org/stable/digikam/

class FTPUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'FTP'
    name = 'FTPUpdater'

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.staticfile_manager = None
        self.embedded = False

        self.url_row = None
        self.filename_row = None
        self.current_download: FTPHost | None = None

    def migrate_v2(self):
        app_config = json_config.read_config_for_app(self.el)
        config = None

        if 'update_manager_config' in app_config:
            old_config = app_config.get('update_manager_config', {})
            config = {
                'url': old_config.get('url', None),
                'filename': old_config.get('filename', None),
            }

        if config:
            Config.set_app_update_config(self.el, self, config)

    def download(self, status_update_cb) -> tuple[str, str]:
        conf = self.get_config()

        if not conf:
            raise Exception('Missing url data for FTPUpdater')

        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception('Missing target asset for FTPUpdater')

        random_name = get_random_string()

        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

        fname = f'{self.download_folder}/{random_name}.appimage'

        server = conf['url'].replace('ftp://', '')

        self.current_download = ftputil.FTPHost(server, 'anonymous', '')
        chunk_size = 8192
        downloaded = 0
        oldperc = 0

        try:
            remote = self.current_download.open(target_asset['item_path'], 'rb')
            with open(fname, 'wb') as local:
                while True:
                    chunk = remote.read(chunk_size)

                    if not chunk:
                        break

                    local.write(chunk)
                    downloaded += len(chunk)
                    
                    # Calculate and display percentage
                    percent = (downloaded / target_asset['size'])
                    roundedperc = round(percent * 100)
                    if roundedperc != oldperc:
                        status_update_cb(percent)
                        oldperc = roundedperc

        except Exception as e:
            raise DownloadInterruptedException

        if self.current_download:
            self.current_download.close()
            self.current_download = None

        file_hash = get_file_hash(None, 'md5', file_path=fname)
        return fname, file_hash

    def cancel_download(self):
        if self.current_download:
            try:
                self.current_download.close()
            except Exception as e:
                pass
            finally:
                self.current_download = None

    def cleanup(self):
        if os.path.exists(self.download_folder):
            shutil.rmtree(self.download_folder)

    def fetch_target_asset(self):
        conf = self.get_config()
        pattern = conf['filename']
        matching_file = None

        server = conf['url'].replace('ftp://', '')
        with ftputil.FTPHost(server, 'anonymous', '') as ftp_host:
            # Parse the pattern to separate directory path from filename pattern
            parts = pattern.split('/')
            base_path = '/'
            wildcards_start = -1
            
            # Find where wildcards start
            for i, part in enumerate(parts):
                if '*' in part or '?' in part:
                    wildcards_start = i
                    break
            
            if wildcards_start > 0:
                base_path = '/'.join(parts[:wildcards_start])
            else:
                base_path = '/'.join(parts)
                if ftp_host.path.isfile(base_path):
                    size = ftp_host.path.getsize(base_path)
                    return {
                        'item_path': base_path, 
                        'size': size
                    }

                return None
            
            # Recursively find all matching files

            def find_matches(current_path, remaining_parts):
                """Recursively traverse directories to find matches."""
                if not remaining_parts:
                    return
                
                current_pattern = remaining_parts[0]
                
                try:
                    items = ftp_host.listdir(current_path)
                except:
                    return
                
                for item in items:
                    item_path = ftp_host.path.join(current_path, item)
                    logging.debug('found ' + str(item_path))
                    
                    # Check if item matches current pattern
                    if fnmatch.fnmatch(item, current_pattern):
                        if len(remaining_parts) == 1:
                            # Last pattern part - check if it's a file
                            if ftp_host.path.isfile(item_path):
                                logging.debug('FTPUpdater: Found mathing item ' + str(item_path))
                                size = ftp_host.path.getsize(item_path)

                                return {
                                    'item_path': item_path, 
                                    'size': size
                                }
                        else:
                            # More patterns to match - recurse into directory
                            if ftp_host.path.isdir(item_path):
                                return find_matches(item_path, remaining_parts[1:])
            
            # Start searching from base path
            pattern_parts = [p for p in parts[wildcards_start:] if p]
            matching_file = find_matches(base_path, pattern_parts)
            
        if not matching_file:
            logging.info("FTPUpdater: No files found matching the pattern")
            return None

        logging.debug(f'Found 1 matching asset: {matching_file["item_path"]}')
        return matching_file

    def is_update_available(self):
        target_asset = self.fetch_target_asset()

        if not target_asset:
            return False

        old_size = os.path.getsize(self.el.file_path)
        is_size_different = target_asset['size'] != old_size
        return is_size_different

    def load_form_rows(self, embedded=None):
        config = self.get_config()
        ftp_url = config.get('url')
        filename = config.get('filename')
        
        self.url_row = AdwEntryRowDefault(
            text=(ftp_url),
            icon_name='gl-earth-symbolic',
            sensitive=(not embedded),
            title=_('Server URL')
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
            url = self.url_row.get_text()

        if self.filename_row:
            filename = self.filename_row.get_text()

        return {
            'url': url,
            'filename': filename,
        }
    
    def validate_config(self, config):
        if not config.get('url', '').startswith('ftp://'):
            raise Exception(f'Invalid {self.name} url')


