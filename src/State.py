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

    def get__(self, key: str):
        return self.props[key] if key in self.props else None

    def connect__(self, key: str, cb: Callable):
        if not key in self.propscb:
            self.propscb[key] = []

        self.propscb[key].append(cb)


state = State()
