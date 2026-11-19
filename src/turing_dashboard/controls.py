# SPDX-License-Identifier: GPL-3.0-or-later
"""Same-user Unix-socket page controls; no global keyboard capture."""
import fcntl
import os
from pathlib import Path
import socket
import stat

COMMANDS = ('next', 'previous', 'pin', 'auto')


def runtime_directory():
    base = Path(os.environ.get('XDG_RUNTIME_DIR', Path.home() / '.cache'))
    directory = base / 'turing-dashboard'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('Controls directory must be private and owned by this user')
    return directory


class ControlServer:
    def __enter__(self):
        directory = runtime_directory()
        self.path = directory / 'control.sock'
        self.lock = os.open(directory / 'control.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists() or self.path.is_symlink():
                info = self.path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise OSError('Refusing to replace a non-socket control path')
                self.path.unlink()
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                self.socket.bind(str(self.path))
                self.path.chmod(0o600)
                self.socket.setblocking(False)
            except BaseException:
                self.socket.close()
                raise
            return self
        except BaseException:
            os.close(self.lock)
            raise

    def commands(self):
        result = []
        for _ in range(32):
            try:
                message = self.socket.recv(128).decode('ascii')
            except BlockingIOError:
                break
            except UnicodeDecodeError:
                continue
            if message in COMMANDS:
                result.append(message)
        return result

    def __exit__(self, *_):
        self.socket.close()
        try:
            self.path.unlink(missing_ok=True)
        finally:
            os.close(self.lock)


def send(command):
    if command not in COMMANDS:
        raise ValueError('Unknown page control')
    path = runtime_directory() / 'control.sock'
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('Control socket must be private and owned by this user')
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.sendto(command.encode('ascii'), str(path))


class PageController:
    def __init__(self, count, seconds, now):
        self.count, self.seconds = count, seconds
        self.page, self.pinned = 0, False
        self.deadline = now + seconds
        self.seen_alerts = set()

    def update(self, now, commands=(), alerts=()):
        # alerts are (page, stable_key, message, severity); manual pin always wins.
        new = [item for item in alerts if (item[0], item[1]) not in self.seen_alerts and item[3] >= 2]
        self.seen_alerts = {(item[0], item[1]) for item in alerts}
        for command in commands:
            if command == 'next':
                self.page = (self.page + 1) % self.count
            elif command == 'previous':
                self.page = (self.page - 1) % self.count
            elif command == 'pin':
                self.pinned = True
            elif command == 'auto':
                self.pinned = False
            self.deadline = now + self.seconds
        if not commands and not self.pinned and new:
            self.page = max(new, key=lambda item: item[3])[0]
            self.deadline = now + self.seconds
        elif not self.pinned and now >= self.deadline:
            self.page = (self.page + 1) % self.count
            self.deadline = now + self.seconds
        return self.page
