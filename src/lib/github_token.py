import gi

from .constants import APP_ID

try:
    gi.require_version('Secret', '1')
    from gi.repository import Secret
except (ValueError, ImportError):
    Secret = None

KEYRING_AVAILABLE = Secret is not None
_ATTRIBUTES = {'purpose': 'github-token'}
if KEYRING_AVAILABLE:
    _SCHEMA = Secret.Schema.new(
        APP_ID + '.github-token', Secret.SchemaFlags.NONE, {'purpose': Secret.SchemaAttributeType.STRING}
    )


def load_github_token():
    if not KEYRING_AVAILABLE:
        return ''
    return Secret.password_lookup_sync(_SCHEMA, _ATTRIBUTES, None) or ''


def save_github_token(token):
    if not token:
        removed = Secret.password_clear_sync(_SCHEMA, _ATTRIBUTES, None)
        return removed or not Secret.password_search_sync(_SCHEMA, _ATTRIBUTES, Secret.SearchFlags.NONE, None)

    return Secret.password_store_sync(
        _SCHEMA, _ATTRIBUTES, Secret.COLLECTION_DEFAULT, 'Gear Lever GitHub token', token, None
    )
