import time
import logging
from .lib.async_utils import _async
from .lib.utils import get_gsettings, send_notification
from .lib.json_config import read_config_for_app
from .lib.costants import UPDATES_AVAILABLE_LABEL, ONE_UPDATE_AVAILABLE_LABEL
from gi.repository import Gio
from .providers.AppImageProvider import AppImageProvider
from .models.UpdateManager import UpdateManagerChecker

class BackgroudUpdatesFetcher():
    # INTERVAL = 3600 * 3
    # FIRST_RUN_INTERVAL = 60 * 5

    INTERVAL = 10
    FIRST_RUN_INTERVAL = 5
    _is_running = False
    
    def is_enabled():
        return get_gsettings().get_boolean('fetch-updates-in-background')
    
    def start():
        if BackgroudUpdatesFetcher._is_running:
            return 
    
        BackgroudUpdatesFetcher._is_running = True

        logging.debug('Starting updates fetcher')

        time.sleep(BackgroudUpdatesFetcher.FIRST_RUN_INTERVAL)
        BackgroudUpdatesFetcher.fetch()

        while True:
            time.sleep(BackgroudUpdatesFetcher.INTERVAL)
            BackgroudUpdatesFetcher.fetch()
            
    def fetch():
        logging.warn('Fetching updates in the background')

        if not BackgroudUpdatesFetcher.is_enabled():
            logging.warn('Update fetching is disabled! Quitting...')
            return
        
        provider = AppImageProvider()
        installed = provider.list_installed()
        updates_available = 0

        for el in installed:
            app_conf = read_config_for_app(el)
            update_url = app_conf.get('update_url', None)

            manager = UpdateManagerChecker.check_url(update_url, el)

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

            send_notification(
                Gio.Notification.new(content)
            )
        else:
            logging.warn('No available updates found')
            
        
    
    
    