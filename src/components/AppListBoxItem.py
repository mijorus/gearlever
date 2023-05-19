from urllib import request
from gi.repository import Gtk, Adw, Gdk, GObject, Pango, GLib
from typing import Dict, List, Optional
from ..lib.utils import cleanhtml
from ..lib.async_utils import idle, _async
import re

from ..models.AppListElement import AppListElement, InstalledStatus
from ..providers.providers_list import providers


class AppListBoxItem(Gtk.ListBoxRow):
    def __init__(self, list_element: AppListElement, load_icon_from_network=False, alt_sources: List[AppListElement] = [], **kwargs):
        super().__init__(**kwargs)

        self._app: AppListElement = list_element
        self._alt_sources: List[AppListElement] = alt_sources

        col = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        col.set_css_classes(['app-listbox-item'])

        self.image_container = Gtk.Box()
        col.append(self.image_container)

        app_details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        app_details_box.append(
            Gtk.Label(
                label=f'<b>{cleanhtml(list_element.name).replace("&", "")}</b>',
                halign=Gtk.Align.START,
                use_markup=True,
                max_width_chars=70,
                ellipsize=Pango.EllipsizeMode.END
            )
        )

        desc = list_element.description if len(list_element.description) else ''
        app_details_box.append(
            Gtk.Label(
                label=cleanhtml(desc), 
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

        provider_icon_box = Gtk.Button(css_classes=['provider-icon'])
        provider_icon = Gtk.Image(resource=providers[list_element.provider].small_icon)
        provider_icon.set_pixel_size(18)
        provider_icon_box.set_child(provider_icon)
        col.append(provider_icon_box)

        self.set_child(col)

        if self._app.installed_status in [InstalledStatus.UPDATING, InstalledStatus.INSTALLING]:
            self.set_opacity(0.5)

    def load_icon(self, load_from_network: bool = False):
        image = providers[self._app.provider].get_icon(self._app, load_from_network=load_from_network)
        image.set_pixel_size(45)
        self.image_container.append(image)

    def set_update_version(self, text: Optional[str]):
        self.update_version.set_visible(text != None)
        self.update_version.set_label(text if text else '')