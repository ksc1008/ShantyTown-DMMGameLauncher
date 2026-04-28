"""Hardware identifiers sent to ``/launch/cl``.

The reference PS1 sends two fixed SHA256 hex strings as ``hdd_serial`` and
``motherboard`` — every user submits the same values. We replicate that
behavior verbatim here so the request matches what DMM has been seeing.
The MAC address is the only field that's actually unique per machine.
"""

from __future__ import annotations

import psutil

from .models import HardwareIds

DUMMY_HDD_SERIAL = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
DUMMY_MOTHERBOARD = "487578a3684a308fca6319f990c3f18db162efcfe97ba8e441864f01deb68d42"

_ZERO_MAC = "00:00:00:00:00:00"


def get_mac_address() -> str:
    """Return the first active interface's MAC, lowercase, colon-separated.

    Raises:
        RuntimeError: If no active adapter with a non-zero MAC is found.
    """
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    for iface, st in stats.items():
        if not st.isup:
            continue
        for addr in addrs.get(iface, []):
            if addr.family != psutil.AF_LINK:
                continue
            raw = addr.address
            if not raw:
                continue
            mac: str = str(raw).replace("-", ":").lower()
            if mac and mac != _ZERO_MAC and len(mac) == 17:
                return mac
    raise RuntimeError("No active network adapter with a MAC address was found.")


def get_default_hardware_ids() -> HardwareIds:
    """Build the ``HardwareIds`` payload the launch endpoint expects."""
    return HardwareIds(
        mac_address=get_mac_address(),
        hdd_serial=DUMMY_HDD_SERIAL,
        motherboard=DUMMY_MOTHERBOARD,
    )
