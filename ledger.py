import os
import subprocess
import sys


def _relaunch_windowed() -> bool:
    """Explorer double-click starts py.exe with a console; hop to pyw/pythonw."""
    if sys.platform != "win32":
        return False
    if len(sys.argv) > 1:
        return False
    if os.environ.get("LEDGER_WINDOWED") == "1":
        return False
    exe = sys.executable
    name = os.path.basename(exe).lower()
    folder = os.path.dirname(exe)
    if name in {"pythonw.exe", "pyw.exe"}:
        return False
    if name == "python.exe":
        target = os.path.join(folder, "pythonw.exe")
    elif name == "py.exe":
        target = os.path.join(folder, "pyw.exe")
    else:
        return False
    if not os.path.isfile(target):
        return False
    env = os.environ.copy()
    env["LEDGER_WINDOWED"] = "1"
    script = os.path.abspath(__file__)
    subprocess.Popen([target, script], cwd=os.path.dirname(script), env=env, close_fds=True)
    return True


if __name__ == "__main__":
    if _relaunch_windowed():
        raise SystemExit(0)
    from grid_ledger.cli import main

    raise SystemExit(main())
