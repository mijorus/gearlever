import dbus
import re
import os
import time
import logging
import gi
import hashlib

from .costants import APP_ID
from .async_utils import idle

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


# def gtk_image_from_url(url: str, image: Gtk.Image) -> Gtk.Image:
#     response = requests.get(url, timeout=10)
#     response.raise_for_status()

#     loader = GdkPixbuf.PixbufLoader()
#     loader.write_bytes(GLib.Bytes.new(response.content))
#     loader.close()

#     image.clear()
#     image.set_from_pixbuf(loader.get_pixbuf())
#     return image


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
    logging.debug(f'Copying {file.get_path()} to {destination.get_path()}')
    return file.copy(
        destination,
        Gio.FileCopyFlags.OVERWRITE,
        None, None, None, None
    )


def get_file_hash(file: Gio.File, alg='md5') -> str:
    with open(file.get_path(), 'rb') as f:
        if alg == 'md5':
            return hashlib.md5(f.read()).hexdigest()
        elif alg == 'sha1':
            return hashlib.sha1(f.read()).hexdigest()

    raise Exception('Invalid hash requested')

def send_notification(notification=Gio.Notification, tag=None):
    if not tag:
        tag = str(time.time_ns())
    Gio.Application().get_default().send_notification(tag, notification)


def get_gsettings() -> Gio.Settings:
    return Gio.Settings.new(APP_ID)


def create_dict(*args: str):
    return dict({i: eval(i) for i in args})


def portal(interface: str, bus_name: str='org.freedesktop.portal.Desktop', object_path: str='/org/freedesktop/portal/desktop') -> dbus.Interface:
    bus = dbus.SessionBus()
    obj = bus.get_object(bus_name, object_path)
    inter = dbus.Interface(obj, interface)

    return inter


def get_element_without_overscroll(arr: list, index: int):
    """
    Returns the element at the given index in the array.
    If the index is out of bounds, the index is wrapped around
    to the range of valid indices for the array.
    """
    if index < 0:
        index = 0

    if len(arr) == 0:
        raise ValueError("Array must not be empty")
    wrapped_index = index % len(arr)
    return arr[wrapped_index]


def url_is_valid(url: str) -> bool:
    url_regex = re.compile(
        r'^(?:http|https)://'  # http:// or https://
        r'[a-z0-9]+(?:-[a-z0-9]+)*'  # domain name
        r'(?:\.[a-z]{2,})+'  # .com, .net, etc.
        r'(?:/?|[/?]\S+)$'  # /, /path, or /path?query=string
    , re.IGNORECASE)

    return True if url_regex.match(url) else False

def remove_special_chars(filename, replacement=""):
    """Removes special characters from a filename and replaces them with a chosen character.

    Args:
        filename: The filename to be sanitized.
        replacement: The character to replace special characters with (default: "_").

    Returns:
        The sanitized filename.
    """
    # Regular expression to match special characters (excluding alphanumeric, underscore, and dot)
    pattern = r"[^\w\._]+"
    return re.sub(pattern, replacement, filename)

@idle
def command_output_error(output):
    if 'libfuse' in output:
        output = output.replace('\n', '')
        logging.error(output)

        dialog = Adw.MessageDialog(
            transient_for=get_application_window(),
            heading=_('Error')
        )

        dialog.set_body(f'AppImages require FUSE to run. You might still be able to run it with --appimage-extract-and-run in the command line arguments. \n\nClick the link below for more information. \n<a href="https://github.com/AppImage/AppImageKit/wiki/FUSE">https://github.com/AppImage/AppImageKit/wiki/FUSE</a>')
        dialog.set_body_use_markup('True')
        dialog.add_response('okay', _('Okay'))

        dialog.present()