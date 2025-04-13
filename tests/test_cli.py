import unittest
import subprocess

class TestGearLever(unittest.TestCase):
    def runCommand(self, command: list[str]):
        output = subprocess.run(['flatpak', 'run', 'it.mijorus.gearlever', *command], stdout=subprocess.PIPE)
        output.check_returncode()
        output_str = output.stdout.decode()
        
        print(output_str)
        return output_str
        
    def test_list_installed(self):
        self.runCommand(['--list-installed'])