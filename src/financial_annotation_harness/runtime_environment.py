"""One-shot Windows environment inventory. No utilization monitor or polling."""
import csv
import io
import json
import platform
import shutil
import subprocess


def windows_memory_bytes():
    """Physical RAM from Windows API without requiring WMI permissions."""
    try:
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (name, ctypes.c_uint64) for name in ("total_phys", "available_phys", "total_page", "available_page", "total_virtual", "available_virtual", "extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total_phys
    except (AttributeError, OSError):
        return None
    return None


def command_output(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def environment_snapshot():
    result = {"os": platform.platform(), "ram_bytes": None, "gpus": [], "measurement": "one-shot"}
    if platform.system() == "Windows":
        result["ram_bytes"] = windows_memory_bytes()
    if shutil.which("nvidia-smi"):
        raw = command_output(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
        if raw:
            for row in csv.reader(io.StringIO(raw)):
                if len(row) == 3:
                    result["gpus"].append({"name": row[0].strip(), "vram_mib": int(row[1].strip()), "driver": row[2].strip()})
    if not result["gpus"]:
        result["gpu_note"] = "GPU/VRAM unavailable from nvidia-smi; researcher must supply verified values"
    return result
