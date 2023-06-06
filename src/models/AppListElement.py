from __future__ import annotations
from typing import Optional, Dict, List

from enum import Enum

class InstalledStatus(Enum):
    NOT_INSTALLED = 0
    INSTALLED = 1
    UNINSTALLING = 3
    ERROR = 4
    UNKNOWN = 5
    INSTALLING = 6
    UPDATE_AVAILABLE = 7
    UPDATING = 8

class AppListElement():
    def __init__(self, name: str, description: str, provider: str, installed_status: InstalledStatus, size: float=0):
        self.name: str = name
        self.description: str = description if description.strip() else _('No description provided')
        self.provider: str = provider
        self.installed_status: InstalledStatus = installed_status
        self.size: Optional[float] = size

    def set_installed_status(self, installed_status: InstalledStatus):
        self.installed_status = installed_status
