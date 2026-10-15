"""The raw identifier of the machine the SDK runs on: the ``deviceId`` of every order.

The server binds orders to a device. Nobody configures one (and nobody can): the SDK reads the
operating system's own machine id and sends it as is, so the same machine always has the same
``deviceId`` and the broker sees the real hardware/OS identity (nothing is hashed or invented).

Sources, first that works: macOS ``IOPlatformUUID``, Linux ``/etc/machine-id``, Windows
``MachineGuid``; then the network card's MAC address (``aa:bb:cc:dd:ee:ff``), or the host name
when the system can only offer a random address.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import uuid
from functools import lru_cache
from pathlib import Path

__all__ = ["get_device_id"]

def _macos_uuid() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603  (fixed command, no user input)
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if "IOPlatformUUID" in line:
            return line.split("=", 1)[-1].strip().strip('"') or None
    return None


def _linux_machine_id() -> str | None:
    for name in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(name).read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if value:
            return value
    return None


def _windows_machine_guid() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0]) or None
    except OSError:
        return None


def _mac_or_host() -> str:
    """The MAC address of a network card, or the host name if the address would be random."""
    node = uuid.getnode()
    if (node >> 40) & 1:  # multicast bit set: Python made the number up
        return platform.node() or "unknown-host"
    return ":".join(f"{(node >> shift) & 0xFF:02x}" for shift in range(40, -8, -8))


def _machine_source() -> str:
    """The most specific machine identity available, as text."""
    if sys.platform == "darwin":
        found = _macos_uuid()
    elif sys.platform.startswith("linux"):
        found = _linux_machine_id()
    elif sys.platform in ("win32", "cygwin"):
        found = _windows_machine_guid()
    else:
        found = None
    return found or _mac_or_host()


@lru_cache(maxsize=1)
def get_device_id() -> str:
    """The raw machine id of this computer, e.g. ``11111111-2222-3333-4444-555555555555``.

    Returns:
        The operating system's machine id as the OS reports it (macOS ``IOPlatformUUID``,
        Linux machine-id, Windows ``MachineGuid``), else the MAC address / host name. Read once
        per process.
    """
    return _machine_source()
