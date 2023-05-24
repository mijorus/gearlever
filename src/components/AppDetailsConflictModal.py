from typing import Optional, Callable
from gi.repository import Gtk, GObject, Adw
from ..lib.utils import get_application_window
from ..providers.AppImageProvider import AppImageListElement, AppImageUpdateLogic

class AppDetailsConflictModal(Adw.MessageDialog):
    def __init__(self):
        super().__init__(
            get_application_window(), 
            _('Conflict with "{app_name}"').format(app_name=self.app_list_element.name), 
            _('There is already an app with the same name, how do you want to proceed?')
        )

        self.add_response('cancel', _('Cancel'))
        self.set_response_appearance('cancel', Adw.ResponseAppearance.DESTRUCTIVE)

        self.add_response(AppImageUpdateLogic.REPLACE.value, _('Replace'))
        self.add_response(AppImageUpdateLogic.KEEP.value, _('Keep both'))