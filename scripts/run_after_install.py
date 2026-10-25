"""Wait for the known installer, then continue the project without requiring an open terminal."""
import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--installer-pid", type=int, required=True)
args = parser.parse_args()
kernel = ctypes.windll.kernel32
kernel.OpenProcess.restype = ctypes.c_void_p
kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
kernel.CloseHandle.argtypes = [ctypes.c_void_p]
handle = kernel.OpenProcess(0x1000, False, args.installer_pid)
if handle:
    while True:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            break
        time.sleep(10)
    kernel.CloseHandle(handle)
python = ROOT / ".env-gpu/python.exe"
print("Installer exited; checking project imports", flush=True)
check = subprocess.run([str(python), "-c", "import transformers, sentence_transformers, chromadb, fitz; print('imports ready')"], cwd=ROOT)
if check.returncode:
    (ROOT / "work/launcher_failed.txt").write_text("Dependency import check failed; inspect build and install logs.")
    raise SystemExit(check.returncode)
status_path = ROOT / "work/model_transfer_status.json"
if (ROOT / "work/range_download.pid").exists():
    print("Waiting for checksum-verified model transfer", flush=True)
    while not status_path.exists() or json.loads(status_path.read_text()).get("status") != "complete":
        transfer_pid = int((ROOT / "work/range_download.pid").read_text())
        transfer_handle = kernel.OpenProcess(0x1000, False, transfer_pid)
        alive = False
        if transfer_handle:
            code = ctypes.c_ulong()
            alive = bool(kernel.GetExitCodeProcess(transfer_handle, ctypes.byref(code))) and code.value == 259
            kernel.CloseHandle(transfer_handle)
        if not alive:
            (ROOT / "work/launcher_failed.txt").write_text("Model transfer stopped before verification; inspect range download log.")
            raise SystemExit(1)
        time.sleep(10)
print("Starting automated stages", flush=True)
raise SystemExit(subprocess.run([str(python), "-u", "-X", "utf8", str(ROOT / "scripts/continue_build.py")], cwd=ROOT).returncode)
