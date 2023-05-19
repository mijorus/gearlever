
from .AppListElement import AppListElement
from typing import Optional

class FlatpakHistoryElement():
    def __init__(self, commit: str='', subject: str='', date: str=''):
        self.commit = commit
        self.subject = subject
        self.date = date

class AppUpdateElement():
    def __init__(self, app_id: str, size: Optional[str], to_verison: Optional[str], **kwargs):
        self.id: str = app_id
        self.size: Optional[str] = size
        self.to_version: Optional[str] = to_verison
        self.extra_data: dict = {}

        for k, v in kwargs.items():
            self.extra_data[k] = v

class SearchResultsItems():
    def __init__(self, app_id: str, list_elements: list[AppListElement]):
        self.id: str = app_id
        self.list_elements: list[AppListElement] = list_elements

class ProviderMessage():
    def __init__(self, message: str, severity: str):
        """ severity can be: info, warn, danger """
        self.message = message
        self.severity = severity