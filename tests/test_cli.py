import unittest
import subprocess
import os
import shutil
import requests

class TestGearLever(unittest.TestCase):
    def setUp(self):
        self.cwd = os.environ.get('GITHUB_WORKSPACE', os.path.dirname(os.path.abspath(__file__)))
        self.testfilesPath = os.path.join(self.cwd, 'testfiles')
        self.isGh = os.environ.get('GITHUB_WORKSPACE') != None
        self.installPath = os.path.join(os.getenv('HOME'), 'AppImages')
        self.download_dir = os.path.join(self.cwd, 'testfiles')

    def tearDown(self):
        pass
    
    def runCommand(self, command: list[str]):
        print('Running ' + ' '.join(['flatpak', 'run', 'it.mijorus.gearlever', *command]))
        output = subprocess.run(['flatpak', 'run', 'it.mijorus.gearlever', *command], stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE)
        output_err = output.stderr.decode().strip()

        if output_err:
            print('Error:', output.stderr.decode())

        output.check_returncode()
        output_str = output.stdout.decode()
        return output_str

    def installApp(self, appname, app_url=None):
        if app_url:
            self.download_file(app_url, appname)

        self.runCommand(['--integrate', os.path.join(self.download_dir, appname), '-y'])
        installed = self.runCommand(['--list-installed', '-v'])
        self.assertIn(appname, self.get_installed_files())
        self.assertIn(appname, installed)

        self.runCommand(['--remove', os.path.join(self.installPath, appname), '-y'])
        self.assertNotIn(appname, self.get_installed_files())

    def download_file(self, url, filename):
        """
        Downloads a file from a given URL and saves it to /tmp/gearlever with the specified filename.

        Args:
            url (str): The URL of the file to download.
            filename (str): The name to save the downloaded file as.

        Raises:
            Exception: If there are any issues during the download or saving process.
        """
        # Define the directory path
        save_directory = self.download_dir
        
        # Ensure the directory exists
        os.makedirs(save_directory, exist_ok=True)
        
        # Full path to save the file
        file_path = os.path.join(save_directory, filename)
        
        try:
            # Download the file
            print(f"Downloading {url}")
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an error for HTTP errors

            # Get the total file size from headers (if available)
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0

            # Write the file to the specified location
            with open(file_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

                    downloaded_size += len(chunk)

                    # Calculate and display the download percentage
                    if total_size > 0:  # Prevent division by zero
                        percentage = (downloaded_size / total_size) * 100
                        print(f"Download progress: {percentage:.2f}%", end="\r")

            print(f"File downloaded and saved to {file_path}")
        except Exception as e:
            print(f"An error occurred: {e}")
            raise

    def get_icon_files(self):
        return os.listdir(os.path.join(self.installPath, '.icons'))

    def get_installed_files(self):
        return os.listdir(os.path.join(self.installPath))

    def test_list_installed(self):
        self.runCommand(['--list-installed'])
    
    def test_generic_apps(self):
        self.installApp('zen.AppImage')

    def test_install(self):
        appname = 'mudlet.appimage'
        self.runCommand(['--integrate', os.path.join(self.download_dir, appname), '-y'])
        installed = self.runCommand(['--list-installed', '-v'])
        self.assertIn(appname, self.get_installed_files())
        self.assertIn('mudlet.png', self.get_icon_files())
        self.assertIn(appname, installed)

        self.runCommand(['--remove', os.path.join(self.installPath, appname), '-y'])
        self.assertNotIn(appname, self.get_installed_files())
        self.assertNotIn('mudlet.png', self.get_icon_files())

    def test_install_dwarfs(self):
        appname = 'citron.appimage'
        self.runCommand(['--integrate', os.path.join(self.download_dir, appname), '-y'])
        installed = self.runCommand(['--list-installed', '-v'])
        self.assertIn(appname, self.get_installed_files())
        self.assertIn('citron.svg', self.get_icon_files())
        self.assertIn(appname, installed)

        self.runCommand(['--remove', os.path.join(self.installPath, appname), '-y'])
        self.assertNotIn(appname, self.get_installed_files())
        self.assertNotIn('citron', self.get_icon_files())

        # Test dwarfs with symbolic links
        appname = 'ghostty.appimage'
        self.runCommand(['--integrate', os.path.join(self.download_dir, appname), '-y'])
        self.assertIn(appname, self.get_installed_files())
        self.runCommand(['--remove', os.path.join(self.installPath, appname), '-y'])

    def test_fetch_updates(self):
        appname = 'citron-old.appimage'
        self.runCommand(['--integrate', os.path.join(self.download_dir, appname), '-y'])
        self.assertIn(appname, self.get_installed_files())

        updates_list = self.runCommand(['--list-updates'])
        self.assertIn(appname, updates_list)

        self.runCommand(['--remove', os.path.join(self.installPath, appname), '-y'])

    def test_fetch_updates_explicit_url(self):
        appname = 'beeper.appimage'
        self.runCommand(['--integrate', 'https://api.beeper.com/desktop/download/linux/x64/stable/com.automattic.beeper.desktop', os.path.join(self.download_dir, appname), '-y'])
        self.runCommand(['--set-update-url', os.path.join(self.installPath, appname), '--url', 'https://api.beeper.com/desktop/download/linux/x64/stable/com.automattic.beeper.desktop'])
        self.assertIn(appname, self.get_installed_files())

        updates_list = self.runCommand(['--list-updates'])
        self.assertIn(appname, updates_list)

        self.runCommand(['--remove', os.path.join(self.installPath, appname), '-y'])

    def test_with_appimageextract(self):
        # Test apps using appimage-extract
        appname = 'navicat.appimage'
        self.runCommand(['--integrate', os.path.join(self.download_dir, appname), '-y'])
        self.assertIn(appname, self.get_installed_files())
        self.runCommand(['--remove', os.path.join(self.installPath, appname), '-y'])