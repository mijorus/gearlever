from gi.repository import Gtk, Pango, GObject, Gio, GdkPixbuf, GLib, Adw


class FilterEntry(Gtk.SearchBar):
    def __init__(self, label, capture: Gtk.Widget = None, maximum_size=600):
        super().__init__()
    
        self.search_entry = Gtk.SearchEntry(placeholder_text=label, hexpand=True)
        self.search_entry.get_first_child().set_from_icon_name("funnel-outline-symbolic")

        clamp = Adw.Clamp(child=self.search_entry, maximum_size=maximum_size,hexpand=True, margin_top=5, margin_bottom=5)

        self.set_search_mode(False)
        self.set_key_capture_widget(capture)
        self.set_child(clamp)

        self.connect_entry(self.search_entry)
        self.props.margin_bottom = 5
