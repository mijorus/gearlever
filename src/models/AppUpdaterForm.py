from abc import ABC, abstractmethod
from gi.repository import Gtk, Adw, GObject, Gio, Gdk

class AppUpdaterForm(ABC):
    @abstractmethod
    def get_form_rows(): list[Adw.EntryRow]
        pass