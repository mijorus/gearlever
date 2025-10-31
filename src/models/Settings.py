from ..lib.constants import APP_ID
from gi.repository import Gio  # noqa


class Settings():
    settings = Gio.Settings.new(schema_id=APP_ID)