"""Bounded logs and a controlled process group/job for an explicitly chosen CLI."""
from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

LOG_LIMIT = 1024 * 1024  # Per stream, bytes. Excess output is drained, not retained.

# The trusted gate cannot start user code before the parent attaches its job.
WINDOWS_GATE = """
import json, subprocess, sys
args = json.load(sys.stdin)
try:
    child = subprocess.Popen(args, stdin=subprocess.DEVNULL)
except OSError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(127)
raise SystemExit(child.wait())
"""


class WindowsJob:
    """Kill-on-close job; descendants inherit it before any agent can run.

    https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
    """
    def __init__(self):
        from ctypes import wintypes as w
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, args, restype in (
            ("CreateJobObjectW", [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            ("SetInformationJobObject", [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            ("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL),
            ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
            ("QueryInformationJobObject", [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            ("OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            ("CloseHandle", [w.HANDLE], w.BOOL),
        ):
            func = getattr(self.api, name)
            func.argtypes, func.restype = args, restype

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", w.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("processes", w.DWORD), ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        handle = self.api.OpenProcess(0x100 | 0x1, False, process.pid)  # SET_QUOTA | TERMINATE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(handle)

    def stop(self):
        from ctypes import wintypes as w
        if not self.api.TerminateJobObject(self.handle, 124):
            raise ctypes.WinError(ctypes.get_last_error())

        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_longlong * 4), ("faults", w.DWORD), ("total", w.DWORD),
                        ("active", w.DWORD), ("terminated", w.DWORD)]

        deadline = time.monotonic() + 5
        while True:
            info = Accounting()
            if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not info.active:
                return
            if time.monotonic() >= deadline:
                raise OSError("Windows job termination did not complete")
            time.sleep(.01)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def run_command(args, directory, timeout, *, log_limit=LOG_LIMIT):
    """Return only after stopping the owned group/job and collecting bounded logs.

    POSIX uses a new session and kills its process group, including workers left
    by an exited parent. This is process lifecycle control, not an OS sandbox:
    a deliberately detached/brokered process needs external containment.
    """
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be an integer between 1 and 3600 seconds")
    if type(log_limit) is not int or log_limit < 1:
        raise ValueError("positive log limit required")
    if os.name not in ("nt", "posix"):
        raise OSError("process containment unavailable on this platform")
    process, job, threads = None, None, []
    stats, failures = {}, []
    with tempfile.TemporaryDirectory(prefix="meal-binder-logs-") as temporary:
        root = Path(temporary)

        def drain(stream, name):
            total, stored = 0, 0
            try:
                with stream, (root / name).open("wb") as output:
                    while chunk := stream.read(65536):
                        total += len(chunk)
                        retained = chunk[:max(0, log_limit - stored)]
                        output.write(retained)
                        stored += len(retained)
                stats[name] = {"octets_lus": total, "octets_conserves": stored, "tronque": total > stored}
            except BaseException as exc:
                failures.append(exc)

        try:
            if os.name == "nt":
                job = WindowsJob()
                process = subprocess.Popen([sys.executable, "-I", "-c", WINDOWS_GATE], cwd=directory,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                job.assign(process)
            else:
                process = subprocess.Popen(args, cwd=directory, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                thread = threading.Thread(target=drain, args=(stream, name), daemon=True)
                thread.start()
                threads.append(thread)
            if os.name == "nt":
                process.stdin.write(json.dumps(args).encode("utf-8"))
                process.stdin.close()
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                code = 124
        finally:
            try:
                if job is not None:
                    job.stop()
                elif process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            finally:
                if job is not None:
                    job.close()
                if process is not None:
                    # Also covers a Windows gate that could not be assigned.
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    if process.stdin is not None and not process.stdin.closed:
                        process.stdin.close()
                    for thread in threads:
                        thread.join(timeout=5)
                    if any(thread.is_alive() for thread in threads):
                        raise OSError("agent streams still open after group/job termination")
                    for stream in (process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
        if failures:
            raise OSError("agent log capture failed") from failures[0]
        return code, (root / "stdout").read_bytes(), (root / "stderr").read_bytes(), stats
