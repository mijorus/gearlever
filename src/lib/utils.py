import re
import os
import time
import logging
import gi
import requests
import hashlib

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw, Gdk, GLib, GdkPixbuf  # noqa


def key_in_dict(_dict: dict, key_lookup: str, separator='.'):
    """
        Searches for a nested key in a dictionary and returns its value, or None if nothing was found.
        key_lookup must be a string where each key is deparated by a given "separator" character, which by default is a dot
    """
    keys = key_lookup.split(separator)
    subdict = _dict

    for k in keys:
        if isinstance(subdict, dict):
            subdict = subdict[k] if (k in subdict) else None

        if subdict is None:
            break

    return subdict


def log(s):
    logging.debug(s)


def add_page_to_adw_stack(stack: Adw.ViewStack, page: Gtk.Widget, name: str, title: str, icon: str):
    stack.add_titled(page, name, title)
    stack.get_page(page).set_icon_name(icon)


# as per recommendation from @freylis, compile once only
_html_clearner = None


def cleanhtml(raw_html: str) -> str:
    global _html_clearner

    if not _html_clearner:
        _html_clearner = re.compile('<.*?>')

    cleantext = re.sub(_html_clearner, '', raw_html)
    return cleantext


def gtk_image_from_url(url: str, image: Gtk.Image) -> Gtk.Image:
    response = requests.get(url, timeout=10)
    response.raise_for_status()

    loader = GdkPixbuf.PixbufLoader()
    loader.write_bytes(GLib.Bytes.new(response.content))
    loader.close()

    image.clear()
    image.set_from_pixbuf(loader.get_pixbuf())
    return image


def set_window_cursor(cursor: str):
    for w in Gtk.Window.list_toplevels():
        if isinstance(w, Gtk.ApplicationWindow):
            w.set_cursor(Gdk.Cursor.new_from_name(cursor, None))
            break


def get_application_window() -> Gtk.ApplicationWindow:
    for w in Gtk.Window.list_toplevels():
        if isinstance(w, Gtk.ApplicationWindow):
            return w


def qq(condition, is_true, is_false):
    return is_true if condition else is_false


def get_giofile_content_type(file: Gio.File):
    return file.query_info('standard::', Gio.FileQueryInfoFlags.NONE, None).get_content_type()


def gio_copy(file: Gio.File, destination: Gio.File):
    return file.copy(
        destination,
        Gio.FileCopyFlags.OVERWRITE,
        None, None, None, None
    )


def get_file_hash(file: Gio.File):
    with open(file.get_path(), 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def send_notification(notification=Gio.Notification, tag=None):
    if not tag:
        tag = str(time.time_ns())
    Gio.Application().get_default().send_notification(tag, notification)


def get_gsettings() -> Gio.Settings:
    return Gio.Settings.new('it.mijorus.boutique')


def create_dict(*args: str):
    return dict({i: eval(i) for i in args})
