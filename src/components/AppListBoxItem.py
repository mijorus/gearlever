from urllib import request
from gi.repository import Gtk, Pango, GObject
from typing import Dict, List, Optional
from ..lib.async_utils import idle, _async

from ..models.AppListElement import AppListElement, InstalledStatus
from ..providers.providers_list import appimage_provider


class AppListBoxItem(Gtk.ListBoxRow):
    __gsignals__ = {
        "details-clicked": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self, list_element: AppListElement, show_details_btn=False, **kwargs):
        super().__init__(**kwargs)

        self._app: AppListElement = list_element
        self.details_btn: Optional[Gtk.Button] = None

        col = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        col.set_css_classes(['app-listbox-item'])

        self.image_container = Gtk.Box()
        col.append(self.image_container)

        app_details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        app_details_box.append(
            Gtk.Label(
                label=list_element.name,
                halign=Gtk.Align.START,
                # use_markup=True,
                css_classes=['heading'],
                max_width_chars=70,
                ellipsize=Pango.EllipsizeMode.END
            )
        )

        if list_element.description:
            app_details_box.append(
                Gtk.Label(
                    label=list_element.description, 
                    halign=Gtk.Align.START,
                    lines=1,
                    max_width_chars=100, 
                    ellipsize=Pango.EllipsizeMode.END,
                )
            )

        self.update_version = Gtk.Label(
            label='',
            margin_top=3,
            halign=Gtk.Align.START,
            css_classes=['subtitle'],
            visible=False
        )

        app_details_box.append(self.update_version)
        app_details_box.set_hexpand(True)
        col.append(app_details_box)

        if show_details_btn:
            self.details_btn = Gtk.Button(icon_name='right-symbolic',
                                     valign=Gtk.Align.CENTER)
            
            col.append(self.details_btn)
        
        self.set_child(col)

        if self._app.installed_status in [InstalledStatus.UPDATING, InstalledStatus.INSTALLING]:
            self.set_opacity(0.5)

    def load_icon(self):
        image = appimage_provider.get_icon(self._app)
        self.set_icon(image)
    
    def set_icon(self, image: Gtk.Image):
        image.set_pixel_size(45)
        self.image_container.append(image)

    def set_update_version(self, text: Optional[str]):
        self.update_version.set_visible(text != None)
        self.update_version.set_label(text if text else '')