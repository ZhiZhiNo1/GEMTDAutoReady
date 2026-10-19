"""Virtual-desktop cleanup helpers."""

from pyvda import VirtualDesktop, get_virtual_desktops


def delete_empty_desktops():
    """Remove empty virtual desktops while always retaining one desktop."""
    desktops = get_virtual_desktops()
    if len(desktops) <= 1:
        return

    current = VirtualDesktop.current()
    nonempty = [
        desktop
        for desktop in desktops
        if desktop.apps_by_z_order(include_pinned=False)
    ]
    keep = next(
        (desktop for desktop in nonempty if desktop.id == current.id),
        nonempty[0] if nonempty else current,
    )

    for desktop in reversed(desktops):
        if desktop.id == keep.id:
            continue
        if desktop.apps_by_z_order(include_pinned=False):
            continue
        desktop.remove(fallback=keep)
