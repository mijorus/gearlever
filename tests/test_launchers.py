import unittest

from src.lib.launchers import (
    desktop_id_from_filename,
    launcher_filename_part,
    name_tokens,
    pick_primary_launcher,
)


class TestNameTokens(unittest.TestCase):
    def test_ignores_versions_architectures_and_extensions(self):
        self.assertEqual(
            name_tokens('digiKam-8.8.0-Qt6-x86-64.appimage'),
            {'digikam'}
        )

        self.assertEqual(
            name_tokens('/tmp/zen_browser.AppImage'),
            {'zen', 'browser'}
        )

    def test_strips_desktop_extension(self):
        self.assertEqual(
            name_tokens('org.kde.showfoto.desktop'),
            {'org', 'kde', 'showfoto'}
        )


class TestPickPrimaryLauncher(unittest.TestCase):
    def test_digikam_prefers_digikam_over_showfoto(self):
        launchers = [
            ('org.kde.digikam', 'digiKam'),
            ('org.kde.showfoto', 'showFoto'),
        ]

        self.assertEqual(
            pick_primary_launcher('digiKam-8.8.0-Qt6-x86-64.appimage', launchers),
            0
        )

        # The order the files are extracted in must not matter
        self.assertEqual(
            pick_primary_launcher('digiKam-8.8.0-Qt6-x86-64.appimage', list(reversed(launchers))),
            1
        )

    def test_dayon_prefers_the_app_entry(self):
        launchers = [
            ('Dayon_Assisted', 'Dayon! (Assisted)'),
            ('Dayon', 'Dayon!'),
        ]

        self.assertEqual(
            pick_primary_launcher('Dayon-1.9.2-x86_64.appimage', launchers),
            1
        )

    def test_prefers_the_simplest_entry_when_nothing_matches(self):
        self.assertEqual(
            pick_primary_launcher('zzz.appimage', [
                ('com.example.long.name', 'Long Name'),
                ('com.example.one', 'One'),
            ]),
            1
        )

    def test_keeps_the_earliest_entry_on_a_full_tie(self):
        launchers = [
            ('com.example.one', 'One'),
            ('com.example.two', 'Two'),
        ]

        self.assertEqual(
            pick_primary_launcher('unrelated-name.appimage', launchers),
            0
        )

    def test_single_launcher(self):
        self.assertEqual(
            pick_primary_launcher('mudlet.appimage', [('mudlet', 'Mudlet')]),
            0
        )


class TestFileNames(unittest.TestCase):
    def test_desktop_id_from_filename(self):
        self.assertEqual(
            desktop_id_from_filename('/tmp/org.kde.digikam.desktop'),
            'org.kde.digikam'
        )

    def test_launcher_filename_part(self):
        self.assertEqual(
            launcher_filename_part('org.kde.showfoto'),
            'org.kde.showfoto'
        )
        self.assertEqual(
            launcher_filename_part('Dayon! (Assisted)'),
            'dayonassisted'
        )
        self.assertEqual(launcher_filename_part(''), 'launcher')
        self.assertEqual(
            launcher_filename_part('a' * 200),
            'a' * 80
        )


if __name__ == '__main__':
    unittest.main()
