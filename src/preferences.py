import gi
import dbus

from .lib.costants import APP_ID

gi.require_version('Gtk', '4.0')

from gi.repository import Adw, Gtk, Gio  # noqa

class Preferences(Adw.PreferencesWindow):
    def __init__(self, **kwargs) :
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new(APP_ID)
        page1 = Adw.PreferencesPage()
        general_preference_group = Adw.PreferencesGroup(name=_( 'General'))

        toggle_cats_row = Adw.ActionRow(title=_('Use images of cats'))
        toggle_cat = Gtk.Switch(valign=Gtk.Align.CENTER)

        toggle_cats_row.add_suffix(toggle_cat)
        general_preference_group.add(toggle_cats_row)
        page1.add(general_preference_group)

        self.add(page1)
        self.settings.bind('show-cats', toggle_cat, 'active', Gio.SettingsBindFlags.DEFAULT)
        
        self.settings.connect('changed::show-cats', self.on_settings_changed)
        # self.settings.connect('changed', self.on_settings_changed)


    def on_settings_changed(self, settings: Gio.Settings, key: str):
        print(key + ' changed:' + str(settings.get_boolean(key) ))