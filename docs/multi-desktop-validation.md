# Multi-desktop lifecycle validation

The multi-desktop entry point owns only desktops returned by its own create calls.
Cleanup never uses names or desktop numbers as ownership evidence. Each window's
original desktop, per-window pin state, placement and topmost state are captured
before unpinning/moving it. All discovered window generations are tracked, not
only the latest Dota/Heybox handle. An application pinned across all desktops is
rejected without changing that application-wide setting.

Shutdown closes the coordinator under the same lock used for capture/click/move,
then restores windows before deleting owned empty desktops. Late operations are
rejected. Failed restoration records and owned desktops are retained for retry.
The normal exit, Ctrl+C, Ctrl+F1, main-thread exception, worker exception, console
close callback and atexit hook all converge on this cleanup. Console close is
best effort within Windows' termination deadline; force-killing the process,
power loss or an indefinitely blocked native API cannot guarantee restoration.
If the user deletes an original destination during execution, restoration may
fail: the failure is logged and the managed desktops are retained.

## Automated checks

Run from the repository root, including on non-Windows hosts:

```sh
python -m unittest discover -s tests -p 'test_virtual_desktop_lifecycle.py' -v
python -m compileall -q main.py scripts utils tests
```

Tests execute the actual coordinator/entry-point function definitions extracted
with AST, with Windows/COM services replaced by fakes. This avoids importing
Windows-only packages or triggering main.py's global hooks on a test host.
These are lifecycle regression tests, not a real COM/Windows integration test.
The existing screenshot CLI checks require their own screenshot inputs and are
not part of these tests.

## Windows manual acceptance (not yet executed)

1. Keep at least three existing desktops, including an intentionally empty one.
   Place Dota and Heybox on different existing desktops. Record their desktop,
   position, minimized/maximized state, topmost and per-window pin state.
2. Start `python scripts/main_multi_desktops.py`. Verify exactly two new desktops
   appear and recognition/click operations return to the startup desktop.
3. Repeat with normal monitor completion, Ctrl+F1 and Ctrl+C. Verify both surviving
   windows return to their own original desktops/states and only the newly
   created empty desktops disappear. The original empty desktop must survive.
4. Repeat with an injected monitor exception and second-desktop creation failure.
   Verify rollback and the logged error. Repeat after Dota restarts so that the
   replacement window has a different handle.
5. Put an unrelated window on a newly created desktop while running. On exit,
   verify that desktop and its window remain. Remove an owned desktop manually
   and verify cleanup skips it rather than deleting a desktop by shifted number.
6. Test a per-window pinned client (unpin during operation, restore pin on exit),
   and an application-wide pinned client (reject without changing app pinning).
7. Close the console window. Check restoration/logs, noting Windows can terminate
   the callback before completion. Test with normal and elevated clients and the
   target Windows build; pyvda relies on build-specific Windows COM interfaces.
