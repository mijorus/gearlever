from abc import ABC, abstractmethod
from typing import List, Callable, Dict, Tuple, Optional, TypeVar
from .AppListElement import AppListElement
from .Models import AppUpdateElement, ProviderMessage
from .AppListElement import InstalledStatus
from gi.repository import Gtk, Gio

class Provider(ABC):
    # refresh_installed_status_callback: Callable
    name: str = NotImplemented
    icon: str = NotImplemented
    smail_icon: str = NotImplemented
    general_messages: List[ProviderMessage] = NotImplemented
    update_messages: List[ProviderMessage] = NotImplemented

    @abstractmethod
    def list_installed(self) -> List[AppListElement]:
        pass

    @abstractmethod
    def is_installed(self, el: AppListElement, alt_sources: list[AppListElement]=[]) -> Tuple[bool, Optional[AppListElement]]:
        pass

    @abstractmethod
    def get_icon(self, AppListElement, repo: str=None, load_from_network: bool=False) -> Gtk.Image:
        pass

    @abstractmethod
    def uninstall(self, el: AppListElement, c: Callable[[bool], None]):
        pass

    @abstractmethod
    def install(self, el: AppListElement, c: Callable[[bool], None]):
        pass

    @abstractmethod
    def search(self, query: str) -> List[AppListElement]:
        pass

    @abstractmethod
    def get_long_description(self, el: AppListElement) ->  str:
        pass

    @abstractmethod
    def load_extra_data_in_appdetails(self, widget: Gtk.Widget, el: AppListElement):
        pass

    @abstractmethod
    def list_updatables(self) -> List[AppUpdateElement]:
        pass

    @abstractmethod
    def update(self, el: AppListElement, callback: Callable[[bool], None]):
        pass
    
    @abstractmethod
    def update_all(self, callback: Callable[[bool, str, bool], None]):
        pass

    @abstractmethod
    def updates_need_refresh(self) -> bool:
        pass

    @abstractmethod
    def run(self, el: AppListElement):
        pass

    @abstractmethod
    def can_install_file(self, filename: Gio.File) -> bool:
        pass

    @abstractmethod
    def is_updatable(self, app_id: str) -> bool:
        pass

    @abstractmethod
    def install_file(self, list_element: AppListElement):
        pass

    @abstractmethod
    def create_list_element_from_file(self, file: Gio.File) -> AppListElement:
        pass

    @abstractmethod
    def open_file_dialog(self, file: Gio.File, parent: Gtk.Widget):
        pass
    
    @abstractmethod
    def set_refresh_installed_status_callback(self, callback: Optional[Callable[[InstalledStatus, bool], None]]):
        pass

    @abstractmethod
    def get_previews(self, el: AppListElement) -> List[Gtk.Widget]:
        pass

    ## extra details
    @abstractmethod
    def get_installed_from_source(self, el: AppListElement) -> str:
        pass

    @abstractmethod
    def get_available_from_labels(self, el: AppListElement) -> str:
        pass
