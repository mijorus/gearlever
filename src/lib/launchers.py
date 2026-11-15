"""Helpers to deal with AppImages that ship more than one .desktop file.

These helpers are intentionally free of any GTK/GObject dependency so that
they can be unit tested without a display or the application schema.
"""

import os
import re
from typing import Sequence, Set, Tuple


# Tokens that say nothing about which launcher represents the app
_NOISE_TOKENS: Set[str] = {
    'app', 'appimage', 'application', 'binary', 'desktop', 'gtk', 'gtk2',
    'gtk3', 'gtk4', 'linux', 'qt', 'qt5', 'qt6', 'static', 'x64', 'x86',
    'x86_64', 'amd64', 'arm', 'arm64', 'aarch64', 'armhf', 'i386', 'i686',
}

_DESKTOP_EXTENSION_RE = re.compile(r'\.desktop$', re.IGNORECASE)
_APPIMAGE_EXTENSION_RE = re.compile(r'\.(appimage|app)$', re.IGNORECASE)
_VERSION_TOKEN_RE = re.compile(r'^v?\d+(?:[._]\d+)*$')


def name_tokens(value: str) -> Set[str]:
    """Split an app/launcher name into meaningful lowercase tokens.

    Version numbers, architecture and packaging words are dropped so that
    ``digiKam-8.8.0-Qt6-x86-64`` and ``org.kde.digikam`` can be matched.
    """
    if not value:
        return set()

    value = os.path.basename(value.strip())
    value = _APPIMAGE_EXTENSION_RE.sub('', value)
    value = _DESKTOP_EXTENSION_RE.sub('', value)

    tokens: Set[str] = set()

    for token in re.split(r'[^a-z0-9]+', value.lower()):
        if not token or token in _NOISE_TOKENS or _VERSION_TOKEN_RE.match(token):
            continue

        tokens.add(token)

    return tokens


def pick_primary_launcher(appimage_name: str, launchers: Sequence[Tuple[str, str]]) -> int:
    """Return the index of the launcher that best represents the AppImage.

    ``launchers`` is a sequence of ``(desktop_id, Name)`` tuples, usually
    sorted by file name. The entry whose id and name share the most
    meaningful tokens with the AppImage file name wins, then the one with
    the fewest unrelated tokens, then the first one, so the result is
    deterministic.
    """
    if not launchers:
        return 0

    app_tokens = name_tokens(appimage_name)

    def score(indexed_launcher):
        index, (desktop_id, desktop_name) = indexed_launcher
        candidate_tokens = name_tokens(desktop_id) | name_tokens(desktop_name)

        # Prefer the launcher sharing more meaningful tokens with the AppImage
        # name, then the one with fewer unrelated tokens, then the first one.
        return (
            len(candidate_tokens & app_tokens),
            -len(candidate_tokens - app_tokens),
            -index,
        )

    return max(enumerate(launchers), key=score)[0]


def desktop_id_from_filename(path: str) -> str:
    """``/some/org.kde.digikam.desktop`` -> ``org.kde.digikam``."""
    return _DESKTOP_EXTENSION_RE.sub('', os.path.basename(path))


def launcher_filename_part(desktop_id: str) -> str:
    """Build a filesystem-safe suffix to tell launchers apart."""
    part = re.sub(r'[^A-Za-z0-9._-]+', '', desktop_id or '').strip('._-').lower()
    part = part[:80].strip('._-')
    return part or 'launcher'
