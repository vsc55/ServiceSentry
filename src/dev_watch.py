"""
Dev watcher: watches source files and does a full process restart on changes.
Usage: python dev_watch.py
Reads environment from .env.dev (same folder as this script).
"""
import os
import sys
import subprocess
import pathlib

from dotenv import load_dotenv
from watchfiles import watch, DefaultFilter

ROOT = pathlib.Path(__file__).parent

load_dotenv(ROOT / '.env.dev', override=True)


class _SourceFilter(DefaultFilter):
    """Only react to .py / .html / .json changes; ignore generated/runtime dirs."""

    allowed_extensions = ('.py', '.html', '.json')
    _skip = {'.venv', '__pycache__', 'data', 'tests', '.vscode', '.git', '.pytest_cache'}

    def __call__(self, change, path):
        parts = set(pathlib.Path(path).parts)
        if parts & self._skip:
            return False
        return super().__call__(change, path)


def _start() -> subprocess.Popen:
    kwargs: dict = {'cwd': str(ROOT), 'env': os.environ.copy()}
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen([sys.executable, str(ROOT / 'main.py'), '--web'], **kwargs)
    print(f'[watch] started  pid={proc.pid}', flush=True)
    return proc


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == 'win32':
        subprocess.call(
            ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f'[watch] stopped  pid={proc.pid}', flush=True)


if __name__ == '__main__':
    watch_paths = [ROOT / 'lib', ROOT / 'watchfuls', ROOT / 'main.py']
    print(f'[watch] watching {[str(p) for p in watch_paths]}', flush=True)

    proc = _start()
    try:
        for changes in watch(*watch_paths, watch_filter=_SourceFilter(), raise_interrupt=True):
            print(f'[watch] {len(changes)} change(s) detected — restarting…', flush=True)
            _stop(proc)
            proc = _start()
    except KeyboardInterrupt:
        _stop(proc)
        print('[watch] exited.', flush=True)
