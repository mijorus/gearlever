import threading

import gi

from gi.repository import GLib, GObject

# Thank you to https://github.com/linuxmint/webapp-manager
# check out common.py for the idea

# Used as a decorator to run things in the background
def _async(func):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        return thread
    return wrapper

# Used as a decorator to run things in the main loop, from another thread
def idle(func):
    def wrapper(*args, **kwargs):
        GLib.idle_add(func, *args)
    return wrapper