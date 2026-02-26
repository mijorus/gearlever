import logging
import re
from typing import Optional, Callable

from ..lib.constants import TMP_DIR
from ..lib import terminal
from ..lib.json_config import read_config_for_app
from ..providers.AppImageProvider import AppImageListElement

from .UpdateManager import UpdateManager
from .GithubUpdater import GithubUpdater
from .GitlabUpdater import GitlabUpdater
from .CodebergUpdater import CodebergUpdater
from .StaticFileUpdater import StaticFileUpdater
from .FTPUpdater import FTPUpdater
from .ForgejoUpdater import ForgejoUpdater

class UpdateManagerChecker():
    @staticmethod
    def get_models() -> list[UpdateManager]:
        return [StaticFileUpdater, GithubUpdater, GitlabUpdater, CodebergUpdater, FTPUpdater, ForgejoUpdater]

    @staticmethod
    def get_model_by_name(manager_label: str) -> Optional[UpdateManager]:
        item = list(filter(lambda m: m.name == manager_label, 
                                    UpdateManagerChecker.get_models()))

        if item:
            return item[0]

        return None

    @staticmethod
    def check_url_for_app(el: AppImageListElement):
        app_conf = read_config_for_app(el)
        update_url_manager: str | None = app_conf.get('update_url_manager', None)

        model = None
        if update_url_manager:
            model = UpdateManagerChecker.get_model_by_name(update_url_manager)

        return UpdateManagerChecker.check_url(el, model=model)

    @staticmethod
    def check_url(el: Optional[AppImageListElement]=None,
                    model: Optional[UpdateManager]=None) -> Optional[UpdateManager]:

        models = UpdateManagerChecker.get_models()

        if model:
            models = list(filter(lambda m: m is model, models))

        model_url: str | None = None
        embedded_url: str | None = None

        # if url and model:
        #     if model.can_handle_link(url):
        #         model_url = url

        if el:
            embedded_app_data = UpdateManagerChecker.check_app_embedded_url(el)

            if embedded_app_data:
                for m in models:
                    if m.handles_embedded and \
                        embedded_app_data.startswith(m.handles_embedded):

                        logging.debug(f'Checking embedded url with {m.__name__}')
                        model = m
                        # if m.can_handle_link(embedded_app_data):
                        #     embedded_url = embedded_app_data
                        #     break

        if model:
            return model.__init__(model_url, embedded=embedded_url, el=el)
            # if model_url and embedded_url:
            
            # if model_url:
            #     return model(model_url, embedded=embedded_url, el=el)
            
            # if embedded_url:
            #     return model(embedded_url, embedded=embedded_url, el=el)

        return None

    @staticmethod
    def check_app_embedded_url(el: AppImageListElement) -> Optional[str]:
        readelf_out = terminal.sandbox_sh(['readelf', '--string-dump=.upd_info', '--wide', el.file_path])
        readelf_out = readelf_out.replace('\n', ' ') + ' '

        # Github url
        # example value: " String dump of section '.upd_info':   [     0]  gh-releases-zsync|neovim|neovim|latest|nvim-linux-x86_64.appimage.zsync "
        pattern_gh = r"gh-releases-zsync\|.*(.zsync)"
        matches = re.search(pattern_gh, readelf_out)

        if matches:
            return matches[0].strip()

        # Static url
        # example value: " String dump of section '.upd_info':   [     0]  zsync|https://gitlab.com/api/v4/projects/24386000/packages/generic/librewolf/latest/LibreWolf.x86_64.AppImage.zsync "
        pattern_link = r"\szsync\|http(.*)\s"
        matches = re.search(pattern_link, readelf_out)

        if matches:
            return matches[0].strip()

        return None

