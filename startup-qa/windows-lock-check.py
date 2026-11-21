"""Hold a real Windows directory handle open while running production rollback."""
import ctypes
import json
from ctypes import wintypes
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

here = Path(__file__).resolve().parent
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]

with TemporaryDirectory(prefix="学霸回滚 ") as tmp:
    root = Path(tmp)
    workspace = root / "workspace"
    backup = root / "backups" / "before-k12-18"
    workspace.mkdir()
    backup.mkdir(parents=True)
    (workspace/"history.txt").write_text("untouched locked workspace")
    (backup/"history.txt").write_text("restored study history")
    transaction = {"phase": "testing", "backup": str(backup), "previous": {"runtimeId": "previous"}}
    (root/"upgrade.json").write_text(json.dumps(transaction), encoding="utf-8")

    # Allow reads and writes, deny sharing DELETE as Windows does with the reported busy directory.
    handle = kernel.CreateFileW(str(workspace/"history.txt"), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        subprocess.run(["node", str(here/"windows-lock-check.mjs"), str(root)], check=True, timeout=35)
    finally:
        kernel.CloseHandle(handle)

    location = json.loads((root/"workspace-location.json").read_bytes())
    assert (workspace/"history.txt").read_text() == "untouched locked workspace"
    assert (root/location["name"]/"history.txt").read_text() == "restored study history"
    assert json.loads((root/"upgrade.json").read_bytes())["phase"] == "recovered"
    assert json.loads((root/"active.json").read_bytes()) == transaction["previous"]

    subprocess.run(["node", str(here/"windows-lock-check.mjs"), str(root)], check=True, timeout=35)
    assert json.loads((root/"workspace-location.json").read_bytes()) == location
    print("Rollback and restart passed with the original workspace kept intact.")
