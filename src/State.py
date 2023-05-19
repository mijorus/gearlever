from gi.repository import GObject
from typing import Callable


class State():
    def __init__(self):
        self.props = {}
        self.propscb = {}

    def set__(self, key, value):
        self.props[key] = value
        
        if key in self.propscb:
            for cb in self.propscb[key]:
                cb(value)

    def connect__(self, key: str, cb: Callable):
        if not key in self.propscb:
            self.propscb[key] = []

        self.propscb[key].append(cb)


state = State()
