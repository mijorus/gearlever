import unittest
import subprocess
import os

class TestGearLever(unittest.TestCase):
    def setUp(self):
        self.cwd = os.environ.get('GITHUB_WORKSPACE', '.')
        self.testfilesPath = os.path.join(self.cwd, 'tests', 'testfiles')
        self.isGh = os.environ.get('GITHUB_WORKSPACE') != None
        self.installPath = os.path.join('~', 'AppImages')
        
        if self.isGh:
            self.installPath = os.path.join('/home/runner/AppImages')
    
    def runCommand(self, command: list[str]):
        output = subprocess.run(['flatpak', 'run', 'it.mijorus.gearlever', *command], stdout=subprocess.PIPE)
        output.check_returncode()
        output_str = output.stdout.decode()
        
        print(output_str)
        return output_str
        
    def test_list_installed(self):
        self.runCommand(['--list-installed'])
        
    def test_install(self):
        self.runCommand(['--integrate', os.path.join(self.testfilesPath, 'demo.AppImage'), '-y'])
        installed = self.runCommand(['--list-installed', '-v'])
        appimages = os.listdir(self.installPath)
        self.assertIn('helloworldappimage.appimage', appimages)
        # self.assertIn('helloworldappimage.appimage', installed)

        self.runCommand(['--remove', os.path.join(self.installPath, 'helloworldappimage.AppImage'), '-y'])
        appimages = os.listdir(self.installPath)
        self.assertNotIn('helloworldappimage.appimage', appimages)

    # def test_install_dwarfs(self):
    #     self.runCommand(['--integrate', os.path.join(self.testfilesPath, 'citron_dwarfs.AppImage'), '-y'])
    #     installed = self.runCommand(['--list-installed', '-v'])
    #     appimages = os.listdir(self.installPath)
    #     self.assertIn('citron.appimage', appimages)
    #     self.assertIn('citron.appimage', installed)
