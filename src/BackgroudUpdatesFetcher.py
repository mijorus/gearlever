import time
import logging
from .lib.utils import get_gsettings

class BackgroudUpdatesFetcher():
    INTERVAL = 3600
    
    def is_enabled():
        return get_gsettings().get_boolean('fetch-updates-in-background')
    
    def start():
        while BackgroudUpdatesFetcher.is_enabled():
            time.sleep(INTERVAL)
            BackgroudUpdatesFetcher.fetch()
            
    def fetch():
        logging.warn('Fetching updates in the background')
        if not BackgroudUpdatesFetcher.is_enabled():
            logging.warn('Update fetching is disabled! Quitting...')
            return
            
        
    
    
    