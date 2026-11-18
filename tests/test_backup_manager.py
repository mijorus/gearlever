import unittest
import os
import shutil
import tempfile
import json
import tarfile

from src.lib.backup_manager import BackupManager
from src.lib.ini_config import Config


class MockElement:
    def __init__(self, name, file_path, description="Test app", desktop_file_path=None):
        self.name = name
        self.file_path = file_path
        self.description = description
        self.desktop_file_path = desktop_file_path
        self.exec_arguments = "--verbose"
        self.env_variables = ["FOO=bar"]
        self.version = "1.0.0"
        self.desktop_entry = None


class TestBackupManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="gearlever_backup_test_")
        self.apps_dir = os.path.join(self.test_dir, "Applications")
        os.makedirs(self.apps_dir)

        # Redirect Config.path to test directory
        self.old_config_path = Config.path
        Config.path = os.path.join(self.test_dir, "gearlever.conf")

        # Create dummy AppImage
        self.appimage_path = os.path.join(self.apps_dir, "gearlever_testapp.appimage")
        with open(self.appimage_path, "wb") as f:
            f.write(b"MOCK_APPIMAGE_ELF_BINARY_CONTENT")

        # Create dummy desktop file
        self.desktop_path = os.path.join(self.test_dir, "gearlever_testapp.desktop")
        with open(self.desktop_path, "w", encoding="utf-8") as f:
            f.write(f"""[Desktop Entry]
Name=TestApp
Exec={self.appimage_path} --verbose
TryExec={self.appimage_path}
Icon=applications-other
Type=Application
""")

        # Create dummy app data in portable .config folder
        self.portable_config = f"{self.appimage_path}.config"
        os.makedirs(self.portable_config)
        with open(os.path.join(self.portable_config, "settings.json"), "w") as f:
            f.write('{"theme": "dark"}')

        self.mock_el = MockElement("TestApp", self.appimage_path, desktop_file_path=self.desktop_path)

        # Set fake config in Config parser
        Config.set_app_config(self.mock_el, {"website": "https://example.com"})

    def tearDown(self):
        Config.path = self.old_config_path
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_detect_app_data(self):
        data = BackupManager.detect_app_data(self.mock_el)
        self.assertTrue(len(data) >= 1)
        self.assertTrue(any(d["type"] == "portable_config" for d in data))

    def test_create_and_inspect_backup(self):
        backup_file = os.path.join(self.test_dir, "test_backup.glbackup")
        manifest = BackupManager.create_backup(
            selected_apps=[self.mock_el],
            output_file_path=backup_file,
            include_binaries=True,
            include_app_data=True,
            include_gearlever_config=True
        )

        self.assertTrue(os.path.isfile(backup_file))
        self.assertEqual(len(manifest["apps"]), 1)
        self.assertEqual(manifest["apps"][0]["name"], "TestApp")

        # Inspect
        inspected = BackupManager.inspect_backup(backup_file)
        self.assertEqual(inspected["format_version"], BackupManager.FORMAT_VERSION)
        self.assertEqual(len(inspected["apps"]), 1)
        self.assertEqual(inspected["apps"][0]["name"], "TestApp")
        self.assertTrue(inspected["apps"][0]["has_binary"])

    def test_restore_backup(self):
        backup_file = os.path.join(self.test_dir, "test_backup.glbackup")
        BackupManager.create_backup(
            selected_apps=[self.mock_el],
            output_file_path=backup_file,
            include_binaries=True,
            include_app_data=True,
            include_gearlever_config=True
        )

        # Target restore directory
        restore_target = os.path.join(self.test_dir, "RestoredApps")
        desktop_target = os.path.join(self.test_dir, "applications")
        restored = BackupManager.restore_backup(
            archive_path=backup_file,
            selected_app_names=["TestApp"],
            destination_folder=restore_target,
            restore_app_data=True,
            desktop_dir=desktop_target
        )

        self.assertEqual(len(restored), 1)
        restored_bin = os.path.join(restore_target, "gearlever_testapp.appimage")
        self.assertTrue(os.path.isfile(restored_bin))
        # Check desktop file restored
        restored_dt = os.path.join(desktop_target, "gearlever_testapp.desktop")
        self.assertTrue(os.path.isfile(restored_dt))
        # Check portable data restored
        restored_data_file = os.path.join(f"{restored_bin}.config", "settings.json")
        self.assertTrue(os.path.isfile(restored_data_file))
        with open(restored_data_file) as f:
            content = f.read()
            self.assertIn("dark", content)

    def test_backup_without_binaries(self):
        backup_file = os.path.join(self.test_dir, "test_backup_nobin.glbackup")
        manifest = BackupManager.create_backup(
            selected_apps=[self.mock_el],
            output_file_path=backup_file,
            include_binaries=False,
            include_app_data=True,
            include_gearlever_config=True
        )

        self.assertTrue(os.path.isfile(backup_file))
        self.assertFalse(manifest["apps"][0]["has_binary"])
        self.assertIsNone(manifest["apps"][0]["binary_tar_path"])

        # Check archive size is minimal (only configs)
        self.assertLess(os.path.getsize(backup_file), 50000)

    def test_backup_corrupted_archive_handling(self):
        corrupt_file = os.path.join(self.test_dir, "corrupt.glbackup")
        with open(corrupt_file, "wb") as f:
            f.write(b"NOT_A_TAR_GZ_FILE")

        with self.assertRaises(Exception):
            BackupManager.inspect_backup(corrupt_file)


if __name__ == "__main__":
    unittest.main()
