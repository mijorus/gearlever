import subprocess
import re
import threading
from typing import Callable, List, Union, Optional
from .utils import log
import logging

def sh(command: List[str], return_stderr=False, **kwargs) -> str:
    try:
        cmd = ['flatpak-spawn', '--host', *command]
        
        log(f'Running {command}')
        output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        output.check_returncode()
    except subprocess.CalledProcessError as e:
        if return_stderr:
            return e.stderr.decode()

        raise e

    return re.sub(r'\n$', '', output.stdout.decode() + (output.stderr.decode() if return_stderr else ''))

def sandbox_sh(command: List[str], return_stderr=False, **kwargs) -> str:
    try:
        cmd = [*command]
        
        log(f'Running {command}')
        output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        output.check_returncode()
    except subprocess.CalledProcessError as e:
        if return_stderr:
            return e.stderr.decode()

        raise e

    return re.sub(r'\n$', '', output.stdout.decode() + (output.stderr.decode() if return_stderr else ''))

def threaded_sh(command: List[str], callback: Optional[Callable[[str], None]]=None, return_stderr=False):
    def run_command(command: List[str], callback: Optional[Callable[[str], None]]=None):
        try:
            output = sh(command, return_stderr)

            if callback:
                callback(re.sub(r'\n$', '', output))

        except subprocess.CalledProcessError as e:
            logging.error(e.stderr)
            raise e

    thread = threading.Thread(target=run_command, daemon=True, args=(command, callback, ))
    thread.start()