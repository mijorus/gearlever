import os
import random
from gi.repository import GLib # noqa

APP_ID = 'it.mijorus.gearlever'
APP_NAME = 'gearlever'
FETCH_UPDATES_ARG = 'fetch-updates'
APP_DATA = {
    'PKGDATADIR': ''
}

RUN_ID = ''.join((random.choice('abcdxyzpqr123456789') for i in range(10)))
ONE_UPDATE_AVAILABLE_LABEL = _('1 update available')
UPDATES_AVAILABLE_LABEL = _('{n} updates available')
TMP_DIR = os.path.join(GLib.get_tmp_dir(), APP_ID + '-' + RUN_ID)