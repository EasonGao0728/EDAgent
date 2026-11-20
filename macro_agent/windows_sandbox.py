"""Windows AppContainer with no capability SIDs, fresh identity and a bounded Job.

Only a dedicated project-local Python runtime and a per-invocation work directory
receive ACL grants. No host shell, network capability or inherited credentials.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import time
import uuid
import zipfile

from .common import read_json, write_json


def _within(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("sandbox path must be a child of its project cache")
    return path


def prepare_runtime(project_root):
    root = Path(project_root).resolve()
    runtime = _within(root / ".cache" / "macro-agent" / "python", root / ".cache")
    runtime.mkdir(parents=True, exist_ok=True)
    source = Path(sys.base_prefix)
    version = f"python{sys.version_info.major}{sys.version_info.minor}"
    stamp = runtime / "runtime.json"
    if (not stamp.exists() or read_json(stamp).get("source") != str(source)
            or read_json(stamp).get("python") != sys.version):
        for name in ("python.exe", "python3.dll", f"{version}.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            p = source / name
            if p.exists():
                shutil.copy2(p, runtime / name)
        if not (runtime / "python.exe").exists():
            raise RuntimeError("Windows CPython runtime unavailable")
        shutil.copytree(source / "DLLs", runtime / "DLLs", dirs_exist_ok=True)
        lib = Path(sysconfig.get_path("stdlib"))
        with zipfile.ZipFile(runtime / f"{version}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in lib.rglob("*.py"):
                rel = path.relative_to(lib)
                if not set(rel.parts).intersection({"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "ensurepip"}):
                    archive.write(path, rel.as_posix())
        (runtime / f"{version}._pth").write_text(f"{version}.zip\nDLLs\n.\n", encoding="utf-8")
        write_json(stamp, {"source": str(source), "python": sys.version,
                           "isolation": "AppContainer; no capability SIDs"})
    for name in ("geometry.py", "context_api.py", "worker.py"):
        original, target = Path(__file__).parent / name, runtime / name
        if not target.exists() or hashlib.sha256(original.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
            shutil.copy2(original, target)
    return runtime


def _api():
    if os.name != "nt":
        raise RuntimeError("v0.1 sandbox requires Windows; no unsafe fallback")
    k = C.WinDLL("kernel32", use_last_error=True)
    u = C.WinDLL("userenv", use_last_error=True)
    a = C.WinDLL("advapi32", use_last_error=True)
    u.CreateAppContainerProfile.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_void_p, W.DWORD, C.POINTER(C.c_void_p)]
    u.CreateAppContainerProfile.restype = C.c_long
    u.DeleteAppContainerProfile.argtypes = [W.LPCWSTR]
    u.DeleteAppContainerProfile.restype = C.c_long
    a.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    a.ConvertSidToStringSidW.restype = W.BOOL
    a.FreeSid.argtypes = [C.c_void_p]
    a.FreeSid.restype = C.c_void_p
    for name, args, result in (
        ("LocalFree", [C.c_void_p], C.c_void_p),
        ("CloseHandle", [W.HANDLE], W.BOOL),
        ("InitializeProcThreadAttributeList", [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)], W.BOOL),
        ("UpdateProcThreadAttribute", [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p], W.BOOL),
        ("DeleteProcThreadAttributeList", [C.c_void_p], None),
        ("CreateProcessW", [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.c_void_p, C.c_void_p], W.BOOL),
        ("CreateJobObjectW", [C.c_void_p, W.LPCWSTR], W.HANDLE),
        ("SetInformationJobObject", [W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        ("AssignProcessToJobObject", [W.HANDLE, W.HANDLE], W.BOOL),
        ("ResumeThread", [W.HANDLE], W.DWORD),
        ("WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
        ("TerminateJobObject", [W.HANDLE, W.UINT], W.BOOL),
        ("TerminateProcess", [W.HANDLE, W.UINT], W.BOOL),
        ("GetExitCodeProcess", [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
    ):
        func = getattr(k, name)
        func.argtypes, func.restype = args, result
    return k, u, a


class _Startup(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR),
                ("lpTitle", W.LPWSTR), ("dwX", W.DWORD), ("dwY", W.DWORD),
                ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
                ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD),
                ("dwFillAttribute", W.DWORD), ("dwFlags", W.DWORD),
                ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", C.c_void_p), ("hStdInput", W.HANDLE),
                ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class _StartupEx(C.Structure):
    _fields_ = [("StartupInfo", _Startup), ("lpAttributeList", C.c_void_p)]


class _Process(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


class _Capabilities(C.Structure):
    _fields_ = [("AppContainerSid", C.c_void_p), ("Capabilities", C.c_void_p),
                ("CapabilityCount", W.DWORD), ("Reserved", W.DWORD)]


class _BasicLimits(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_int64), ("PerJobUserTimeLimit", C.c_int64),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", C.c_size_t),
                ("MaximumWorkingSetSize", C.c_size_t), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", C.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class _Limits(C.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", C.c_uint64 * 6),
                ("ProcessMemoryLimit", C.c_size_t), ("JobMemoryLimit", C.c_size_t),
                ("PeakProcessMemoryUsed", C.c_size_t), ("PeakJobMemoryUsed", C.c_size_t)]


def _check(ok):
    if not ok:
        raise C.WinError(C.get_last_error())


def _acl(path, *arguments):
    proc = subprocess.run(["icacls.exe", str(path), *arguments, "/T", "/Q"],
                          capture_output=True, timeout=30, creationflags=0x08000000)
    if proc.returncode:
        raise RuntimeError("sandbox ACL configuration failed: " + proc.stderr.decode(errors="replace")[-1200:])


class WindowsSandbox:
    def __init__(self, project_root, timeout=15, memory_mb=256):
        self.root = Path(project_root).resolve()
        self.timeout = timeout
        self.memory_mb = memory_mb
        self.runtime = prepare_runtime(self.root)

    def run(self, payload):
        work = _within(self.root / ".cache" / "macro-agent" / "jobs" / uuid.uuid4().hex,
                       self.root / ".cache")
        work.mkdir(parents=True)
        write_json(work / "input.json", payload)
        return self._launch(work, self.runtime / "worker.py", [work / "input.json", work / "output.json"])

    def probe(self, source):
        """Run a trusted boundary-test program under the EXACT same OS restrictions."""
        work = _within(self.root / ".cache" / "macro-agent" / "jobs" / uuid.uuid4().hex,
                       self.root / ".cache")
        work.mkdir(parents=True)
        script = work / "probe.py"
        script.write_text(source, encoding="utf-8")
        return self._launch(work, script, [work / "output.json"])

    def _launch(self, work, script, arguments):
        k, u, a = _api()
        profile = "aieda.macro." + uuid.uuid4().hex
        sid, sid_text = C.c_void_p(), W.LPWSTR()
        attributes = None
        pi = _Process()
        job = None
        granted = []
        started = time.monotonic()
        try:
            hr = u.CreateAppContainerProfile(profile, profile, "Macro operator isolated execution", None, 0, C.byref(sid))
            if hr < 0:
                raise RuntimeError(f"CreateAppContainerProfile failed: HRESULT 0x{hr & 0xffffffff:08x}")
            _check(a.ConvertSidToStringSidW(sid, C.byref(sid_text)))
            identity = sid_text.value
            # On data drives the inherited owner ACL can grant only Modify.
            # WRITE_OWNER on our fresh job directory is needed to lower its label.
            _acl(work, "/grant", f"{getpass.getuser()}:(OI)(CI)F")
            for path, rights in ((self.runtime, "RX"), (work, "M")):
                _acl(path, "/grant", f"*{identity}:(OI)(CI){rights}")
                granted.append(path)
            _acl(work, "/setintegritylevel", "(OI)(CI)L")
            size = C.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            _check(k.InitializeProcThreadAttributeList(attributes, 1, 0, C.byref(size)))
            caps = _Capabilities(sid, None, 0, 0)
            _check(k.UpdateProcThreadAttribute(attributes, 0, 0x00020009,
                                               C.byref(caps), C.sizeof(caps), None, None))
            startup = _StartupEx()
            startup.StartupInfo.cb = C.sizeof(startup)
            startup.lpAttributeList = C.cast(attributes, C.c_void_p)
            job = k.CreateJobObjectW(None, None)
            _check(job)
            limits = _Limits()
            limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x8 | 0x2
            limits.BasicLimitInformation.ActiveProcessLimit = 1
            limits.BasicLimitInformation.PerProcessUserTimeLimit = int(self.timeout * 10_000_000)
            limits.ProcessMemoryLimit = self.memory_mb * 1024 * 1024
            _check(k.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
            command = C.create_unicode_buffer(subprocess.list2cmdline(
                [str(self.runtime / "python.exe"), "-I", "-S", str(script), *map(str, arguments)]))
            environment = {key: os.environ[key] for key in
                           ("SystemRoot", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "ALLUSERSPROFILE")
                           if key in os.environ}
            environment.update(TEMP=str(work), TMP=str(work), PYTHONIOENCODING="utf-8")
            env_buffer = C.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(environment.items())) + "\0\0")
            _check(k.CreateProcessW(str(self.runtime / "python.exe"), command, None, None,
                                   False, 0x00080000 | 0x00000400 | 0x08000000 | 0x4,
                                   env_buffer, str(work), C.byref(startup), C.byref(pi)))
            _check(k.AssignProcessToJobObject(job, pi.hProcess))
            if k.ResumeThread(pi.hThread) == 0xffffffff:
                raise C.WinError(C.get_last_error())
            waited = k.WaitForSingleObject(pi.hProcess, int(self.timeout * 1000))
            if waited == 0x102:
                k.TerminateJobObject(job, 124)
                k.WaitForSingleObject(pi.hProcess, 3000)
                result = {"ok": False, "error": "operator wall-time limit exceeded"}
            elif waited != 0:
                raise C.WinError(C.get_last_error())
            else:
                exit_code = W.DWORD()
                _check(k.GetExitCodeProcess(pi.hProcess, C.byref(exit_code)))
                output = work / "output.json"
                if exit_code.value or not output.exists():
                    result = {"ok": False, "error": f"sandbox worker exit={exit_code.value}; output missing={not output.exists()}"}
                elif output.stat().st_size > 1024 * 1024:
                    result = {"ok": False, "error": "output exceeds 1 MiB"}
                else:
                    result = read_json(output)
            result.update(sandbox="windows_appcontainer", capability_count=0,
                          elapsed_seconds=round(time.monotonic() - started, 4),
                          job_directory=str(work))
            return result
        finally:
            if pi.hProcess:
                k.TerminateProcess(pi.hProcess, 125)
                k.WaitForSingleObject(pi.hProcess, 3000)
            for handle in (pi.hThread, pi.hProcess, job):
                if handle:
                    k.CloseHandle(handle)
            if attributes:
                k.DeleteProcThreadAttributeList(attributes)
            if sid_text:
                identity = sid_text.value
                for path in granted:
                    _acl(path, "/remove:g", "*" + identity)
                k.LocalFree(C.cast(sid_text, C.c_void_p))
            if sid:
                a.FreeSid(sid)
                u.DeleteAppContainerProfile(profile)
