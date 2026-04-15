import logging
import re
from typing import Optional, Callable

from ..lib.constants import TMP_DIR
from ..lib import terminal
from ..lib.ini_config import Config
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
    def get_model_by_name(manager_label: str) -> UpdateManager:
        item = list(filter(lambda m: m.name == manager_label, 
                                    UpdateManagerChecker.get_models()))

        if not item:
            raise Exception('Invalid model name: ' + manager_label)

        return item[0]

    @staticmethod
    def check_url_for_app(el: AppImageListElement):
        app_conf = Config.get_app_update_config(el)
        update_url_manager: str | None = app_conf.get('update_url_manager', None)
        embedded_url = None

        model = None
        if update_url_manager:
            model = UpdateManagerChecker.get_model_by_name(update_url_manager)
        else:
            models = UpdateManagerChecker.get_models()
            embedded_app_data = UpdateManagerChecker.check_app_embedded_url(el)

            if embedded_app_data:
                for m in models:
                    if m.handles_embedded and \
                        embedded_app_data.startswith(m.handles_embedded):

                        logging.debug(f'Checking embedded url with {m.__name__}')

                        model = m
                        embedded_url = embedded_app_data
                        break

        if model:
            return model(embedded=embedded_url, el=el)
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

