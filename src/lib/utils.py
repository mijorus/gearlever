import random
import dbus
import re
import os
import time
import logging
import gi
import hashlib
from . import terminal

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
        elif alg == 'sha256':
            return hashlib.sha256(f.read()).hexdigest()

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
    , re.IGNORECASE)

    is_valid = True if url_regex.match(url) else False

    if not is_valid:
        logging.warn(f'Provided url "{url}" is not a valid url')

    return is_valid

def get_random_string():
    return ''.join((random.choice('abcdxyzpqr123456789') for i in range(10)))

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


def show_message_dialog(header, message, markup=False):
    dialog = Adw.MessageDialog(
        transient_for=get_application_window(),
        heading=_('Error'),
        body_use_markup=markup
    )

    dialog.set_body(message)

    dialog.set_body_use_markup(True)
    dialog.add_response('okay', _('Dismiss'))

    dialog.present()


def get_osinfo():
    os_release_file = "/run/host/os-release"

    if not terminal.is_flatpak():
        os_release_file = "/etc/os-release"

    output = ''

    try:
        output = terminal.sandbox_sh(['cat', os_release_file])
    except Exception as e:
        logging.error(e)

    return output

# thank you mate ❤️
# https://github.com/gtimelog/gtimelog/blob/6e4b07b58c730777dbdb00b3b85291139f8b10aa/src/gtimelog/main.py#L159
def make_option(long_name, short_name=None, flags=0, arg=0, arg_data=None, description=None, arg_description=None):
    # surely something like this should exist inside PyGObject itself?!
    option = GLib.OptionEntry()
    option.long_name = long_name.lstrip('-')
    option.short_name = 0 if not short_name else short_name.lstrip('-')
    option.flags = flags
    option.arg = int(arg)
    option.arg_data = arg_data
    option.description = description
    option.arg_description = arg_description
    return option