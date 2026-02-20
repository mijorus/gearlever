from urllib import request
from gi.repository import Gtk, Pango, GObject
from typing import Dict, List, Optional
from ..lib.async_utils import idle, _async
from ..lib.utils import gnu_naturalsize

from ..models.AppListElement import InstalledStatus
from ..providers.AppImageProvider import AppImageListElement
from ..providers.providers_list import appimage_provider


class AppListBoxItem(Gtk.ListBoxRow):
    __gsignals__ = {
        "details-clicked": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self, list_element: AppImageListElement, show_details_btn=False, **kwargs):
        super().__init__(**kwargs)

        self._app: AppImageListElement = list_element
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
        )

        app_details_box.append(self.update_version)
        app_details_box.set_hexpand(True)
        col.append(app_details_box)

        if show_details_btn:
            self.details_btn = Gtk.Button(icon_name='gl-right-symbolic',
                                     valign=Gtk.Align.CENTER)

            col.append(self.details_btn)

        self.update_available_btn = Gtk.Button(
            icon_name='gl-software-update-available-symbolic',
            valign=Gtk.Align.CENTER,
            css_classes=['flat'],
            sensitive=False,
            visible=False
        )

        col.append(self.update_available_btn)
        
        self.set_child(col)

        if self._app.installed_status in [InstalledStatus.UPDATING, InstalledStatus.INSTALLING]:
            self.set_opacity(0.5)

    def load_icon(self):
        image = appimage_provider.get_icon(self._app)
        self.set_icon(image)
    
    def set_icon(self, image: Gtk.Image):
        image.set_pixel_size(45)
        self.image_container.append(image)

    def set_update_version(self, text: Optional[str], size: int):
        c = []

        if text:
            c.append(text)
        c.append(gnu_naturalsize(size))
        

        self.update_version.set_visible(True)
        self.update_version.set_label(' · '.join(c))

    def show_updatable_badge(self):
        self.update_available_btn.set_visible(True)