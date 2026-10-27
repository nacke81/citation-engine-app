"""Owned Chrome: throwaway profile, own port, whole process tree killed on exit (Job Object KILL_ON_JOB_CLOSE).
Never attaches to an existing Chrome. Covers crash: if python dies, the OS closes the job handle and kills the tree."""
import os, socket, subprocess, tempfile, time, shutil, urllib.request, ctypes
from ctypes import wintypes
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
k32 = ctypes.WinDLL("kernel32", use_last_error=True); u32 = ctypes.WinDLL("user32")
k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.OpenProcess.restype = wintypes.HANDLE

k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

def _exe_of(pid):
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h: return ""
    try:
        buf = ctypes.create_unicode_buffer(1024); n = wintypes.DWORD(1024)
        return os.path.basename(buf.value) if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally: k32.CloseHandle(h)

def _in_job(pid, job):
    if not job: return False
    h = k32.OpenProcess(0x1000, False, pid)
    if not h: return False
    try:
        r = wintypes.BOOL(0)
        return bool(k32.IsProcessInJob(h, job, ctypes.byref(r))) and bool(r.value)
    finally: k32.CloseHandle(h)

def pid_alive(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    if not h: return False
    try:
        code = wintypes.DWORD()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
    finally: k32.CloseHandle(h)

def chrome_windows(job=None):
    """Visible titled top-level windows whose owning process image is chrome.exe.
    Each: dict(hwnd, pid, exe, title, owned). owned = process is in the given Job Object (job=None -> False).
    Electron apps share the window class, so the filter is the process image name, not the class."""
    out = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if not u32.IsWindowVisible(h): return True
        n = u32.GetWindowTextLengthW(h)
        if n <= 0: return True
        pid = wintypes.DWORD(0); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        exe = _exe_of(pid.value)
        if exe.lower() != "chrome.exe": return True
        t = ctypes.create_unicode_buffer(n + 1); u32.GetWindowTextW(h, t, n + 1)
        out.append(dict(hwnd=int(h or 0), pid=pid.value, exe=exe, title=t.value, owned=_in_job(pid.value, job)))
        return True
    u32.EnumWindows(EnumProc(cb), 0)
    return out
def window_count(job=None): return len(chrome_windows(job))

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class _BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]
class _ExtLimit(ctypes.Structure):
    _fields_ = [("Basic", _BasicLimit), ("Io", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

def _make_kill_job():
    job = k32.CreateJobObjectW(None, None)
    info = _ExtLimit(); info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError("SetInformationJobObject failed %d" % ctypes.get_last_error())
    return job

class OwnedChrome:
    def __init__(self, profile=None, port=None):
        """profile=None -> throwaway temp profile, deleted on close. profile=<dir> -> persistent profile, kept on close (cookies/logins survive).
        port=None -> free random port."""
        self.proc = None; self.profile = None; self.port = port; self.job = None; self._persist = profile is not None; self._want = profile
    def __enter__(self):
        if self._persist: os.makedirs(self._want, exist_ok=True); self.profile = self._want
        else: self.profile = tempfile.mkdtemp(prefix="ce-s3-chrome-")
        self.port = self.port or _free_port()
        self.job = _make_kill_job()
        args = [CHROME, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}", "--window-position=40,40",
                "--window-size=1400,900", "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble", "--hide-crash-restore-bubble", "about:blank"]
        try:
            self.proc = subprocess.Popen(args)
            h = k32.OpenProcess(0x1F0FFF, False, self.proc.pid)
            if not k32.AssignProcessToJobObject(self.job, h): raise OSError("assign failed %d" % ctypes.get_last_error())
            k32.CloseHandle(h)
            for _ in range(60):
                try: urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1); break
                except Exception: time.sleep(0.5)
            else: raise RuntimeError("owned chrome did not start")
        except BaseException:
            self.close(); raise
        return self
    @property
    def cdp_url(self): return f"http://127.0.0.1:{self.port}"
    def close(self):
        if self.job:
            k32.CloseHandle(self.job); self.job = None      # kills every process in the tree
        if self.proc is not None:
            try: self.proc.wait(timeout=15)
            except Exception: pass
            self.proc = None
        if self.profile and not self._persist:
            for _ in range(10):
                shutil.rmtree(self.profile, ignore_errors=True)
                if not os.path.exists(self.profile): break
                time.sleep(0.5)
            self.profile = None
    def __exit__(self, *a): self.close(); return False
