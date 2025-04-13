import unittest
import subprocess
import os

class TestGearLever(unittest.TestCase):
    def setUp(self):
        self.cwd = os.environ.get('GITHUB_WORKSPACE', '.')
        self.testfilesPath = os.path.join(self.cwd, 'tests', 'testfiles')
    
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
        installed = self.runCommand(['--list-installed'])
        self.assertEqual(('demo.AppImage' in installed), True)