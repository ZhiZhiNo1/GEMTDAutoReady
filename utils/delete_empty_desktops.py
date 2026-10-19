"""Remove only explicitly owned, empty virtual desktops."""

from pyvda import VirtualDesktop, get_virtual_desktops


def delete_empty_desktops(owned_desktops=(), *, fallback=None):
    """Never infer ownership from desktop names, numbers, or emptiness.

    No ownership list means no deletion. Re-resolve IDs because desktop numbers
    change after removal; skip desktops already removed by the user.
    """
    owned_ids = {desktop.id for desktop in owned_desktops}
    fallback = fallback or VirtualDesktop.current()
    for desktop in reversed(get_virtual_desktops()):
        if desktop.id not in owned_ids or desktop.id == fallback.id:
            continue
        if desktop.apps_by_z_order(include_pinned=False):
            continue
        desktop.remove(fallback=fallback)
