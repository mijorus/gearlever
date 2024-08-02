import subprocess
import re
import threading
from typing import Callable, List, Union, Optional
import logging
import os

def host_sh(command: List[str], return_stderr=False, **kwargs) -> str:
    try:
        if os.path.isfile("/.flatpak-info"):
            cmd = ['flatpak-spawn', '--host']
        else:
            cmd = []

        cmd += [*command]
        
        logging.debug(f'Running {cmd}')
        output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        output.check_returncode()
    except subprocess.CalledProcessError as e:
        d = e.stderr.decode()
        if return_stderr:
            return d
        else:
            print(d)

        raise e

    output_string = output.stdout.decode()

    if return_stderr:
        output_string += output.stderr.decode()

    logging.debug(f'Done {cmd}')
    return re.sub(r'\n$', '', output_string)

def sandbox_sh(command: List[str], return_stderr=False, **kwargs) -> str:
    try:
        cmd = [*command]
        
        logging.debug(f'Running {command}')
        output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        output.check_returncode()
    except subprocess.CalledProcessError as e:
        d = e.stderr.decode()
        if return_stderr:
            return d
        else:
            print(d)

        raise e

    output_string = output.stdout.decode()

    if return_stderr:
        output_string += output.stderr.decode()

    logging.debug(f'Done {cmd}')
    return re.sub(r'\n$', '', output_string)

def host_threaded_sh(command: List[str], callback: Optional[Callable[[str], None]]=None, return_stderr=False):
    def run_command(command: List[str], callback: Optional[Callable[[str], None]]=None):
        try:
            output = host_sh(command, return_stderr)

            if callback:
                callback(output)

        except subprocess.CalledProcessError as e:
            logging.error(e.stderr)
            raise e

    thread = threading.Thread(target=run_command, daemon=True, args=(command, callback, ))
    thread.start()