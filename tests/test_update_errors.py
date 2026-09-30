"""Offline update-check regressions; no AppImages are installed or removed."""
import builtins
from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import gi
import requests

# The installed launcher normally sets up gettext and the package path.
builtins.__dict__.setdefault('_', lambda value: value)
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
package = types.ModuleType('gearlever')
package.__path__ = [str(Path(__file__).resolve().parents[1] / 'src')]
sys.modules['gearlever'] = package
cli_module = importlib.import_module('gearlever.Cli')
github_module = importlib.import_module('gearlever.models.GithubUpdater')
Cli = cli_module.Cli
GithubUpdater = github_module.GithubUpdater


class UpdateCheckErrors(unittest.TestCase):
    def setUp(self):
        self.app = types.SimpleNamespace(name='Example', file_path='/tmp/example.AppImage')
        self.manager = Mock(name='manager')
        self.manager.name = 'GithubUpdater'
        self.manager.embedded = False
        self.manager.is_update_available.return_value = False
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        for context in [
            patch.object(cli_module.appimage_provider, 'list_installed', return_value=[self.app]),
            patch.object(cli_module.UpdateManagerChecker, 'check_url_for_app', return_value=self.manager),
            patch.object(cli_module, 'check_internet', return_value=True),
            patch.object(cli_module.logging, 'error'),
            redirect_stdout(self.stdout), redirect_stderr(self.stderr),
        ]:
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def test_successful_no_update(self):
        self.assertEqual(Cli.list_updates([]), [])
        self.assertIn('No updates available', self.stdout.getvalue())
        self.assertEqual(self.stderr.getvalue(), '')

    def test_failure_names_app_and_exits_nonzero(self):
        self.manager.is_update_available.side_effect = requests.HTTPError('403 rate limit exceeded')
        with self.assertRaises(SystemExit) as error:
            Cli.list_updates([])
        self.assertEqual(error.exception.code, 1)
        self.assertIn('Update check failed for Example: 403', self.stderr.getvalue())
        self.assertNotIn('No updates available', self.stdout.getvalue())

    def test_json_failure_keeps_stdout_parseable(self):
        self.manager.is_update_available.side_effect = requests.Timeout('Request timed out')
        with self.assertRaises(SystemExit):
            Cli.list_updates(['--json'])
        result = json.loads(self.stdout.getvalue())
        self.assertEqual(result['updates'], [])
        self.assertEqual(result['errors'][0]['name'], 'Example')
        self.assertEqual(result['errors'][0]['error'], 'Request timed out')

    def test_json_success_contract_unchanged(self):
        Cli.list_updates(['--json'])
        self.assertEqual(json.loads(self.stdout.getvalue()), {'schema_version': 1, 'updates': []})

    def test_manager_creation_failure_is_reported(self):
        with patch.object(cli_module.UpdateManagerChecker, 'check_url_for_app', side_effect=ValueError('Invalid source')):
            with self.assertRaises(SystemExit):
                Cli.list_updates([])
        self.assertIn('Example: Invalid source', self.stderr.getvalue())

    def test_partial_failure_keeps_successful_results(self):
        self.manager.is_update_available.return_value = True
        other = types.SimpleNamespace(name='Broken', file_path='/tmp/broken.AppImage')
        failed = Mock()
        failed.is_update_available.side_effect = requests.ConnectionError('Connection failed')
        with patch.object(cli_module.appimage_provider, 'list_installed', return_value=[self.app, other]), \
             patch.object(cli_module.UpdateManagerChecker, 'check_url_for_app', side_effect=[self.manager, failed]), \
             patch.object(Cli, '_make_app_json', return_value={'name': 'Example'}):
            with self.assertRaises(SystemExit):
                Cli.list_updates(['--json'])
        result = json.loads(self.stdout.getvalue())
        self.assertEqual(result['updates'], [{'name': 'Example'}])
        self.assertEqual(result['errors'][0]['name'], 'Broken')

    def test_update_all_does_not_download_after_failed_check(self):
        self.manager.is_update_available.side_effect = requests.HTTPError('404 Not Found')
        with patch.object(cli_module.appimage_provider, 'update_from_url') as download:
            with self.assertRaises(SystemExit) as error:
                Cli.update(['--all', '--yes'])
        self.assertEqual(error.exception.code, 1)
        download.assert_not_called()

    def test_update_all_reuses_successful_check(self):
        self.manager.is_update_available.return_value = True
        with patch.object(cli_module.appimage_provider, 'is_app_running', return_value=False), \
             patch.object(cli_module.appimage_provider, 'update_from_url') as download:
            Cli.update(['--all', '--yes'])
        self.manager.is_update_available.assert_called_once()
        download.assert_called_once()


class GithubFailures(unittest.TestCase):
    def setUp(self):
        self.app = types.SimpleNamespace(name='Example', file_path='/tmp/example.AppImage')
        self.manager = GithubUpdater(self.app)
        self.config = {'repo': 'example/app', 'repo_filename': '*.AppImage', 'allow_prereleases': False}
        context = patch.object(self.manager, 'does_allow_prereleases', return_value=False)
        context.start()
        self.addCleanup(context.stop)

    def test_release_http_errors_propagate(self):
        for status in (401, 403, 404, 500):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                response.url = 'https://api.github.com/repos/example/app/releases/latest'
                with patch.object(self.manager, 'get_config', return_value=self.config), \
                     patch.object(github_module.requests, 'get', return_value=response):
                    with self.assertRaises(requests.HTTPError):
                        self.manager.is_update_available()

    def test_release_connection_and_json_errors_propagate(self):
        for error in (requests.Timeout('timeout'), requests.ConnectionError('offline')):
            with self.subTest(error=type(error).__name__), \
                 patch.object(self.manager, 'get_config', return_value=self.config), \
                 patch.object(github_module.requests, 'get', side_effect=error):
                with self.assertRaises(type(error)):
                    self.manager.is_update_available()
        response = Mock()
        response.json.side_effect = ValueError('Invalid JSON')
        with patch.object(self.manager, 'get_config', return_value=self.config), \
             patch.object(github_module.requests, 'get', return_value=response):
            with self.assertRaises(ValueError):
                self.manager.is_update_available()

    def test_successful_no_matching_asset_keeps_none(self):
        response = Mock()
        response.json.return_value = {'draft': False, 'assets': []}
        with tempfile.NamedTemporaryFile() as appfile:
            self.app.file_path = appfile.name
            with patch.object(self.manager, 'get_config', return_value=self.config), \
                 patch.object(github_module.requests, 'get', return_value=response):
                self.assertIsNone(self.manager.is_update_available())

    def test_zsync_http_error_propagates(self):
        response = requests.Response()
        response.status_code = 403
        response.url = 'https://example.com/app.zsync'
        target = {'asset': {}, 'zsync': {'browser_download_url': response.url}}
        with tempfile.NamedTemporaryFile() as appfile:
            self.app.file_path = appfile.name
            with patch.object(self.manager, 'fetch_target_asset', return_value=target), \
                 patch.object(github_module.requests, 'get', return_value=response):
                with self.assertRaises(requests.HTTPError):
                    self.manager.is_update_available()


if __name__ == '__main__':
    unittest.main()
