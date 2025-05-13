from gi.repository import Gtk, GObject, Adw, Gdk, Gio, Pango, GLib

class AdwEntryRowDefault(Adw.EntryRow):
    def __init__(self, default_text=None, icon_name=None, **kwargs):
        super().__init__(**kwargs)
        self.default_text = default_text
        self.row_btn = None

        if icon_name:
            row_img = Gtk.Image(icon_name=icon_name, pixel_size=self.ACTION_ROW_ICON_SIZE)
            self.add_prefix(row_img)

        if default_text:
            self.row_btn = Gtk.Button(
                icon_name='gl-arrow2-top-right-symbolic', 
                valign=Gtk.Align.CENTER, 
            )
            
            self.row_btn.connect('clicked', self.on_web_browser_open_btn_clicked)
            self.row_btn.set_visible(self.default_text != self.get_text())
            self.connect('changed', self.on_changed)

        self.add_suffix(row_btn)

    def on_reset_default_clicked(self, *args):
        self.set_text(self.default_text)

    def on_changed(self, *args):
        if self.row_btn:
            self.row_btn.set_visible(self.default_text != self.get_text())
