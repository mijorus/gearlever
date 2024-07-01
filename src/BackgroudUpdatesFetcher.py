import time
import logging
from .lib.utils import get_gsettings, send_notification
from .lib.json_config import read_config_for_app
from .lib.costants import UPDATES_AVAILABLE_LABEL, ONE_UPDATE_AVAILABLE_LABEL
from gi.repository import Gio
from .providers.AppImageProvider import AppImageProvider
from .models.UpdateManager import UpdateManagerChecker

class BackgroudUpdatesFetcher():
    INTERVAL = 3600
    
    def is_enabled():
        return get_gsettings().get_boolean('fetch-updates-in-background')
    
    def start():
        BackgroudUpdatesFetcher.fetch()
        settings = get_gsettings()

        if settings.get_boolean('updates-fetcher-running'):
            return

        settings.set_boolean('updates-fetcher-running', True)
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
                print(e)
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
            
        
    
    
    