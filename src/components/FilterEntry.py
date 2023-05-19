from gi.repository import Gtk, Pango, GObject, Gio, GdkPixbuf, GLib, Adw
from typing import Dict, List


class FilterEntry(Gtk.SearchEntry):
    __gsignals__ = {
        "selected-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self, label, capture: Gtk.Widget = None, **kwargs):
        super().__init__(**kwargs)

        self.props.placeholder_text = label
        self.set_key_capture_widget(capture)
        self.get_first_child().set_from_icon_name("funnel-outline-symbolic")
