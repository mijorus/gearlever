import subprocess
import re
import asyncio
import threading
from typing import Callable, List, Union
from .utils import log

_sanitizer = None
def sanitize(_input: str) -> str:
    global _sanitizer

    if not _sanitizer:
        _sanitizer = re.compile(r'[^0-9a-zA-Z]+')

    return re.sub(_sanitizer, " ", _input)

def sh(command: List[str], return_stderr=False) -> str:
    to_check = command if isinstance(command, str) else ' '.join(command)

    try:
        log(f'Running {command}')

        cmd = ['flatpak-spawn', '--host', *command]
        output = subprocess.run(cmd, encoding='utf-8', shell=False, check=True, capture_output=True)
        output.check_returncode()
    except subprocess.CalledProcessError as e:
        print(e.stderr)

        if return_stderr:
            return e.output

        raise e

    return re.sub(r'\n$', '', output.stdout)

def threaded_sh(command: Union[str, List[str]], callback: Callable[[str], None]=None, return_stderr=False):
    to_check = command if isinstance(command, str) else command[0]

    def run_command(command: str, callback: Callable[[str], None]=None):
        try:
            output = sh(command, return_stderr)

            if callback:
                callback(re.sub(r'\n$', '', output))

        except subprocess.CalledProcessError as e:
            log(e.stderr)
            raise e

    thread = threading.Thread(target=run_command, daemon=True, args=(command, callback, ))
    thread.start()