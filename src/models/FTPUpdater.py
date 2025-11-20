import logging
import os
import ftputil
from ftputil.file import FTPFile
from ftputil import FTPHost
import fnmatch
import shutil
from typing import Optional
from urllib.parse import urlsplit, urlencode
from ..lib.utils import get_random_string, get_file_hash


from ..providers.AppImageProvider import  AppImageListElement

from ..models.Models import DownloadInterruptedException
from .UpdateManager import UpdateManager
from .StaticFileUpdater import StaticFileUpdater
from ..components.AdwEntryRowDefault import AdwEntryRowDefault


# Example:
# https://download.kde.org/stable/digikam/

class FTPUpdater(UpdateManager):
    staticfile_manager: Optional[StaticFileUpdater]
    label = 'FTP'
    name = 'FTPUpdater'

    @staticmethod
    def get_url_data(url: str):
        if (not url.startswith('ftp://')):
            return False

        splitted = urlsplit(url)
        if len(splitted.path) < 2:
            return False

        return {
            'server': 'ftp://' + splitted.netloc,
            'path': splitted.path,
        }

    @staticmethod
    def can_handle_link(url: str):
        return FTPUpdater.get_url_data(url) != False


    def __init__(self, url, **kwargs) -> None:
        super().__init__(url, **kwargs)
        self.staticfile_manager = None
        self.set_url(url)
        self.embedded = False
        
        self.url_row = None
        self.filename_row = None
        self.current_download: FTPHost | None = None

    def set_url(self, url: str):
        self.url_data = self.get_url_data(url)
        self.url = url
        self.repo_url_row = None
        self.repo_filename_row = None

    def download(self, status_update_cb) -> tuple[str, str]:
        target_asset = self.fetch_target_asset()
        if not target_asset:
            raise Exception('Missing target asset for FTPUpdater')
        
        if not self.url_data:
            raise Exception('Missing url data for FTPUpdater')

        random_name = get_random_string()

        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

        fname = f'{self.download_folder}/{random_name}.appimage'

        server = self.url_data['server'].replace('ftp://', '')

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
        if not self.url_data:
            return

        pattern = self.url_data['path']
        matching_file = None

        server = self.url_data['server'].replace('ftp://', '')
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

    def is_update_available(self, el: AppImageListElement):
        target_asset = self.fetch_target_asset()

        if not target_asset:
            return False

        old_size = os.path.getsize(el.file_path)
        is_size_different = target_asset['size'] != old_size
        return is_size_different
    
    def load_form_rows(self, update_url, embedded=False): 
        url_data = FTPUpdater.get_url_data(update_url)
        ftp_url = ''
        filename = ''
        
        if url_data:
            ftp_url = url_data['server']
            filename = url_data['path']

        self.url_row = AdwEntryRowDefault(
            text=(ftp_url),
            icon_name='gl-git',
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

    def get_form_url(self, ) -> str:
        if (not self.filename_row) or (not self.url_row):
            return ''
        
        filename = self.filename_row.get_text()
        if filename.startswith('/'):
            filename = filename[1:]
        
        return '/'.join([
            self.url_row.get_text(),
            filename
        ])



