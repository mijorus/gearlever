import time
import logging
from .lib.terminal import sandbox_sh
from .lib.utils import check_internet
from .lib.constants import UPDATES_AVAILABLE_LABEL, ONE_UPDATE_AVAILABLE_LABEL, APP_ID
from .providers.AppImageProvider import AppImageProvider
from .models.UpdateManagerChecker import UpdateManagerChecker

class BackgroudUpdatesFetcher():
    @staticmethod
    def fetch():
        logging.warn('Fetching updates in the background')

        if not check_internet():
            return

        provider = AppImageProvider()
        installed = provider.list_installed()
        updates_available = 0

        for el in installed:
            manager = UpdateManagerChecker.check_url_for_app(el)

            if not manager:
                continue

            logging.debug(f'Found app with update url: {manager.url}')

            try:
                status = manager.is_update_available(el)

                if status:
                    updates_available += 1
            except Exception as e:
                logging.error(e)

        if updates_available:
            content = ''
            if updates_available == 1:
                content = ONE_UPDATE_AVAILABLE_LABEL
            else:
                content = UPDATES_AVAILABLE_LABEL.replace('{n}', str(updates_available))

            expire_time = 1000 * 60 * 10
            open_label = _('Open') + ' Gear Lever'
            result = sandbox_sh(['notify-send', content, f'--action={open_label}', f'--expire-time={expire_time}'])
            if result == '0':
                sandbox_sh(['gearlever'])
        else:
            logging.warn('No available updates found')
            
        
    
    
    