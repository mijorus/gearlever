from gi.repository import Gtk, Pango, GObject
from typing import Optional

from ..models.AppListElement import InstalledStatus
from ..providers.AppImageProvider import AppImageListElement
from ..providers.providers_list import appimage_provider


class AppGridBoxItem(Gtk.FlowBoxChild):
    __gsignals__ = {
        "launch-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
        "update-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
        "remove-app": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (object, )),
    }

    def __init__(self, list_element: AppImageListElement, **kwargs):
        super().__init__(**kwargs)

        self._app: AppImageListElement = list_element

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            css_classes=['app-gridbox-item'],
            width_request=110,
        )

        self.image_container = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)

        self.update_available_icon = Gtk.Image(
            icon_name='gl-software-update-available-symbolic',
            visible=False,
            halign=Gtk.Align.END,
            valign=Gtk.Align.START,
            pixel_size=16,
            css_classes=['grid-update-badge'],
        )

        self.image_overlay = Gtk.Overlay()
        self.image_overlay.set_child(self.image_container)
        self.image_overlay.add_overlay(self.update_available_icon)

        box.append(self.image_overlay)
        box.append(
            Gtk.Label(
                label=list_element.name,
                halign=Gtk.Align.CENTER,
                justify=Gtk.Justification.CENTER,
                wrap=True,
                wrap_mode=Pango.WrapMode.WORD_CHAR,
                lines=2,
                max_width_chars=15,
                ellipsize=Pango.EllipsizeMode.END,
                css_classes=['caption-heading'],
            )
        )

        self.subtitle_label = Gtk.Label(
            label='',
            halign=Gtk.Align.CENTER,
            max_width_chars=15,
            ellipsize=Pango.EllipsizeMode.END,
            css_classes=['caption', 'dim-label'],
            visible=False,
        )
        box.append(self.subtitle_label)

        # shown in place of the actions while an update is running
        self.progress_bar = Gtk.ProgressBar(
            visible=False,
            margin_top=8,
            margin_bottom=8,
            margin_start=10,
            margin_end=10,
        )
        box.append(self.progress_bar)

        # per-card quick actions (launch / update / remove)
        self.launch_btn = Gtk.Button(
            icon_name='gl-media-playback-start-symbolic',
            css_classes=['flat', 'circular'],
            tooltip_text=_('Launch'),
        )

        # terminal apps can't be started from here, same as in AppDetails
        if self._app.desktop_entry and self._app.desktop_entry.getTerminal():
            self.launch_btn.set_sensitive(False)
            self.launch_btn.set_tooltip_text(_('This app runs in the terminal'))

        self.launch_btn.connect('clicked', lambda *_: self.emit('launch-app', self._app))

        self.update_btn = Gtk.Button(
            icon_name='gl-software-update-available-symbolic',
            css_classes=['flat', 'circular'],
            tooltip_text=_('Update'),
            visible=False,
        )
        self.update_btn.connect('clicked', lambda *_: self.emit('update-app', self._app))

        self.remove_btn = Gtk.Button(
            icon_name='gl-user-trash-symbolic',
            css_classes=['flat', 'circular'],
            tooltip_text=_('Remove'),
        )
        self.remove_btn.connect('clicked', lambda *_: self.emit('remove-app', self._app))

        self.actions_box = actions_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=2,
            halign=Gtk.Align.CENTER,
        )
        [actions_box.append(b) for b in [self.launch_btn, self.update_btn, self.remove_btn]]
        box.append(actions_box)

        self.set_child(box)

        if self._app.installed_status in [InstalledStatus.UPDATING, InstalledStatus.INSTALLING]:
            self.set_opacity(0.5)

    def load_icon(self):
        image = appimage_provider.get_icon(self._app)
        self.set_icon(image)

    def set_icon(self, image: Gtk.Image):
        image.set_pixel_size(64)
        self.image_container.append(image)

    def set_update_version(self, text: Optional[str]):
        self.subtitle_label.set_visible(bool(text))
        self.subtitle_label.set_label(text or '')

    def show_updatable_badge(self):
        self.update_available_icon.set_visible(True)
        self.update_btn.set_visible(True)

    def set_busy(self, busy: bool):
        self.actions_box.set_visible(not busy)
        self.progress_bar.set_visible(busy)
        self.progress_bar.set_fraction(0)
        self.set_opacity(0.5 if busy else 1)

    def set_progress(self, fraction: float):
        self.progress_bar.set_fraction(fraction)
