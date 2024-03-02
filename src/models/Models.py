import logging

from .AppListElement import AppListElement
from typing import Optional

class AppUpdateElement():
    def __init__(self, app_id: str, size: Optional[str], to_verison: Optional[str], **kwargs):
        self.id: str = app_id
        self.size: Optional[str] = size
        self.to_version: Optional[str] = to_verison
        self.extra_data: dict = {}

        for k, v in kwargs.items():
            self.extra_data[k] = v

class InternalError(Exception):
    def __init__(self, message: str, *args) -> None:
        super().__init__(*args)
        self.message = message

        logging.error(message)