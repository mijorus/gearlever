import gettext
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gi
import requests

gi.require_version('Adw', '1')
gettext.install('gearlever')

from src.models.GithubUpdater import GithubUpdater


class TestGithubUpdater(unittest.TestCase):
    def test_private_release_check_and_download(self):
        self.check_and_download('github_pat_test')

    def test_anonymous_release_check_and_download(self):
        self.check_and_download('')

    def test_revoked_token_falls_back_to_anonymous_public_updates(self):
        self.check_and_download('github_pat_revoked', revoked=True)

    def check_and_download(self, token, revoked=False):
        repo = 'https://api.github.com/repos/example/tool'
        release_url = f'{repo}/releases/latest'
        cdn = 'https://release-assets.githubusercontent.com/asset'
        content = b'new AppImage data' * 121
        zsync = f'SHA-1: {hashlib.sha1(content).hexdigest()}\n\n'.encode()
        assets = [
            {
                'name': name,
                'id': asset_id,
                'url': f'{repo}/releases/assets/{asset_id}',
                'browser_download_url': f'https://github.com/example/tool/releases/download/v2/{name}',
            }
            for name, asset_id in [('Tool.AppImage', 107), ('Tool.AppImage.zsync', 205)]
        ]
        requests_seen = []

        def send(request, **kwargs):
            url = request.url
            requests_seen.append(url)
            response = requests.Response()
            response.request = request
            response.url = url
            response.status_code = 200

            auth = request.headers.get('Authorization')
            expected_auth = f'Bearer {token}' if token else None
            if url == release_url:
                if revoked and auth:
                    self.assertEqual(auth, expected_auth)
                    response.status_code = 401
                    body = b''
                else:
                    self.assertEqual(auth, None if revoked else expected_auth)
                    body = json.dumps({'draft': False, 'assets': assets}).encode()
            elif token and not revoked and url in [asset['url'] for asset in assets]:
                self.assertEqual(auth, expected_auth)
                self.assertEqual(request.headers['Accept'], 'application/octet-stream')
                response.status_code = 302
                response.headers['Location'] = f'{cdn}/{url.rsplit("/", 1)[-1]}'
                body = b''
            else:
                self.assertNotIn('Authorization', request.headers)
                app_url, zsync_url = (
                    (f'{cdn}/107', f'{cdn}/205') if token and not revoked else
                    tuple(asset['browser_download_url'] for asset in assets)
                )
                body = {app_url: content, zsync_url: zsync}[url]

            response._content = body
            response._content_consumed = True
            response.headers['Content-Length'] = str(len(body))
            return response

        with TemporaryDirectory() as workdir, \
                patch('src.models.GithubUpdater.load_github_token', return_value=token), \
                patch('src.models.UpdateManager.TMP_DIR', workdir), \
                patch.object(requests.adapters.HTTPAdapter, 'send', side_effect=send):
            installed = Path(workdir) / 'installed.AppImage'
            installed.write_bytes(b'old AppImage data')
            updater = GithubUpdater(
                SimpleNamespace(file_path=str(installed)),
                'gh-releases-zsync|example|tool|latest|Tool.AppImage.zsync',
            )

            self.assertTrue(updater.is_update_available())
            filename, asset_id = updater.download(lambda _: None)
            self.assertEqual(asset_id, 107)
            self.assertEqual(Path(filename).read_bytes(), content)

        lookup = [release_url] * (2 if revoked else 1)
        app, sidecar = (
            [[asset['url'], f'{cdn}/{asset["id"]}'] for asset in assets] if token and not revoked else
            [[asset['browser_download_url']] for asset in assets]
        )
        self.assertEqual(requests_seen, lookup + sidecar + lookup + app)
