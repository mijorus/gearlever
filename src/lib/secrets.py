import dbus
import logging
from typing import Callable

def save_secret(label: str, value: str):

    # Connect to the session bus
    bus = dbus.SessionBus()

    # Get the Secret portal object
    secret_portal = bus.get_object('org.freedesktop.portal.Desktop', 
                                '/org/freedesktop/portal/desktop')

    # Get the interface
    secret_iface = dbus.Interface(secret_portal, 'org.freedesktop.portal.Secret')

    # Create a session
    session_handle_path, options = secret_iface.CreateSession({})

    # Store a secret
    attributes = {}
    secret = "my_secret_password"
    secret_iface.StoreSecret(session_handle_path, attributes, label, value, {})

def read_secret(label: str, cb: Callable):
    # Connect to the session bus
    bus = dbus.SessionBus()

    # Get the Secret portal object
    secret_portal = bus.get_object('org.freedesktop.portal.Desktop', 
                                '/org/freedesktop/portal/desktop')

    # Get the interface
    secret_iface = dbus.Interface(secret_portal, 'org.freedesktop.portal.Secret')

    # Create a session
    session_handle_path, options = secret_iface.CreateSession({})

    # Set up the attributes to look for the secret
    # These should match what you used when storing
    attributes = {"attribute1": "value1", "attribute2": "value2"}

    # Function to handle the response
    def on_secret_retrieved(response, result):
        if response == 0:  # Success
            cb(result)
        else:
            logging.error(f"Failed to retrieve secret: {response}")

    secret_iface.RetrieveSecret(session_handle_path, attributes, 
                        reply_handler=on_secret_retrieved,
                        error_handler=lambda e: logging.error(f"Error: {e}"))