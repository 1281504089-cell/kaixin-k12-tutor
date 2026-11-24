"""Finish a staged, signed launcher after the application's normal shutdown."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def same_process(pid, executable, created):
    try:
        process = psutil.Process(pid)
        return (os.path.normcase(process.exe()) == os.path.normcase(executable)
                and abs(process.create_time() - created) < 0.01)
    except psutil.NoSuchProcess:
        return False


def quit_application(pid):
    if sys.platform == "darwin":
        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)(("objc_msgSend", objc))
        target = send(objc.objc_getClass(b"NSRunningApplication"), objc.sel_registerName(b"runningApplicationWithProcessIdentifier:"), pid)
        terminate = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
        if not target or not terminate(target, objc.sel_registerName(b"terminate")):
            raise RuntimeError("The application declined to close; close it normally and retry")
    elif sys.platform == "win32":
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        found = []
        def close(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                if user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE uses the app's normal quit handler.
                    found.append(hwnd)
            return True
        callback = callback_type(close)
        user32.EnumWindows(callback, 0)
        if not found:
            raise RuntimeError("The desktop application has no closable window")
    else:
        raise RuntimeError("Unsupported desktop platform")


def validate_job(job_path):
    job_path = Path(job_path).resolve(strict=True)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    profile = Path(job["profileRoot"]).resolve(strict=True)
    if job_path != profile / "launcher-update.json" or job.get("status") not in {"ready", "restarting", "failed"}:
        raise ValueError("Invalid pending launcher update")
    app = str(Path(job["appExecutable"]).resolve(strict=True))
    pid, created = job["appPid"], job["appCreateTime"]
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        raise ValueError("Invalid application process")
    runtime = Path(job["runtimeRoot"]).resolve(strict=True)
    if runtime.parent.parent != profile or runtime.parent.name != "runtimes":
        raise ValueError("Invalid runtime location")
    installed = json.loads((runtime / "installed.json").read_text(encoding="utf-8"))
    base_id = installed.get("baseRuntimeId", runtime.name)
    import re
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,100}", base_id):
        raise ValueError("Invalid native runtime")
    node = runtime.parent / base_id / ("node/node.exe" if os.name == "nt" else "node/bin/node")
    if Path(job["nodeExecutable"]).resolve(strict=True) != node.resolve(strict=True):
        raise ValueError("Invalid native executable")
    result = subprocess.run([str(node), str(runtime / "launcher/src/shell-update.mjs"), "--validate"],
                            input=json.dumps(job), text=True, encoding="utf-8", capture_output=True, timeout=120,
                            env={k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"})
    if result.returncode:
        raise ValueError("Launcher verification failed: " + result.stderr.strip()[:500])
    return job


def app_is_running(executable):
    for process in psutil.process_iter(["exe"]):
        try:
            if process.info["exe"] and os.path.normcase(process.info["exe"]) == os.path.normcase(executable):
                return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return False


def finish(job, *, wait_only=False):
    app, pid, created = job["appExecutable"], job["appPid"], job["appCreateTime"]
    if same_process(pid, app, created):
        if not wait_only:
            # The API response must reach the old page before its process exits.
            time.sleep(0.5)
            quit_application(pid)
        deadline = time.monotonic() + 60
        while same_process(pid, app, created):
            if time.monotonic() > deadline:
                raise TimeoutError("The application did not close; no launcher files were replaced")
            time.sleep(0.1)
    if app_is_running(app):
        raise RuntimeError("Another application session is running; no launcher files were replaced")
    runtime = Path(job["runtimeRoot"])
    # Allow both macOS codesign phases plus time for the launcher to restore its backup if needed.
    apply_timeout = 660 if sys.platform == "darwin" else 300
    result = subprocess.run([job["nodeExecutable"], str(runtime / "launcher/src/shell-update.mjs"), "--apply"],
                            input=json.dumps(job), text=True, encoding="utf-8", capture_output=True, timeout=apply_timeout,
                            env={k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"})
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:500])
    return job


def relaunch(job):
    environment = dict(os.environ)
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
               "stderr": subprocess.DEVNULL, "cwd": job["profileRoot"], "env": environment}
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen([job["appExecutable"]], **options)


def run_job(args):
    job_path = Path(args.job).resolve()
    # Do not close or relaunch an application until both signed manifests pass.
    try:
        job = validate_job(job_path)
    except Exception as error:
        try:
            state = json.loads(job_path.read_text(encoding="utf-8"))
            if job_path == Path(state["profileRoot"]).resolve() / "launcher-update.json":
                state.update(status="failed", restartRequired=True, error=str(error)[:1000])
                save(job_path, state)
        except (OSError, ValueError, KeyError):
            pass
        return 1
    try:
        if args.detach:
            # The intermediate parent exits before the old Windows taskkill /T tree is stopped.
            subprocess.Popen([sys.executable, __file__, "--job", args.job, "--detached-parent", str(os.getpid())],
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        if args.detached_parent:
            deadline = time.monotonic() + 10
            while psutil.pid_exists(args.detached_parent):
                if time.monotonic() > deadline:
                    raise TimeoutError("The restart helper did not detach")
                time.sleep(0.05)
        finished = finish(job, wait_only=args.wait_only)
    except Exception as error:
        job.update(status="failed", restartRequired=True, error=str(error)[:1000])
        save(job_path, job)
        if not app_is_running(job["appExecutable"]):
            relaunch(job)
        return 1
    relaunch(finished)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument("--wait-only", action="store_true")
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--detached-parent", type=int)
    args = parser.parse_args()
    sys.exit(run_job(args))
