"""Restricted CPython worker; not a general-purpose hostile-code sandbox.

Only one zero-argument solution function over primitive financial data is allowed.
The worker receives no database, Gold labels, provider client, or API credentials.
"""

from __future__ import annotations

import ast
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED_BUILTINS = {"min": min, "max": max, "sum": sum, "len": len, "sorted": sorted,
                    "zip": zip, "all": all, "any": any, "round": round, "abs": abs}
ALLOWED_NODES = {"Module", "FunctionDef", "arguments", "Assign", "Return", "Name", "Constant",
                 "Store", "Load", "UnaryOp", "USub", "UAdd", "Not", "Dict", "List", "Tuple",
                 "Call", "keyword", "Attribute", "BinOp", "Div", "Sub", "Mult", "Add",
                 "IfExp", "Compare", "Gt", "GtE", "Lt", "LtE", "Eq", "NotEq", "ListComp",
                 "DictComp", "GeneratorExp", "Subscript", "comprehension", "Slice", "BoolOp", "And", "Or"}


def inspect_python(code: str, max_chars: int = 20000) -> ast.Module:
    if len(code) > max_chars:
        raise ValueError("Python source exceeds size limit")
    tree = ast.parse(code)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Exactly one function, def solution(), is required")
    fn = tree.body[0]
    if (fn.name != "solution" or fn.decorator_list or fn.returns or fn.args.args or fn.args.posonlyargs
            or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or fn.args.defaults):
        raise ValueError("solution must have no arguments, annotations, or decorators")
    if not fn.body or not isinstance(fn.body[-1], ast.Return):
        raise ValueError("solution must end with return")
    if any(not isinstance(n, (ast.Assign, ast.Return)) for n in fn.body):
        raise ValueError("Only assignments and return are allowed in solution")
    nodes = list(ast.walk(tree))
    if len(nodes) > 2500:
        raise ValueError("AST node budget exceeded")
    for node in nodes:
        if type(node).__name__ not in ALLOWED_NODES:
            raise ValueError(f"Unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or "__" in node.id or node.id == "solution":
                raise ValueError("Private names and recursion are forbidden")
            if isinstance(node.ctx, ast.Store) and node.id in ALLOWED_BUILTINS:
                raise ValueError("Cannot rebind an allowed builtin")
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise ValueError("Nested functions are forbidden")
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float, str, bool, type(None)):
                raise ValueError("Unsupported literal")
            if isinstance(node.value, str) and len(node.value) > 128:
                raise ValueError("String literal too long")
            if type(node.value) in (int, float) and (not math.isfinite(node.value) or abs(node.value) > 10**18):
                raise ValueError("Numeric literal outside supported range")
        if isinstance(node, ast.Attribute):
            if node.attr not in ("get", "values", "keys", "items") or not isinstance(node.value, ast.Name):
                raise ValueError("Only primitive dictionary methods are permitted")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in ALLOWED_BUILTINS:
                    raise ValueError("Call target is not allowed")
            elif not isinstance(node.func, ast.Attribute):
                raise ValueError("Dynamic call targets are forbidden")
            if any(k.arg not in ("key", "reverse") for k in node.keywords):
                raise ValueError("Unsupported keyword argument")
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise ValueError("Assign to a single named variable")
        if isinstance(node, ast.comprehension) and node.is_async:
            raise ValueError("Async comprehension is forbidden")
    return tree


def _memory_limit(megabytes: int):
    """Enforce a per-process limit before executing generated code; fail closed."""
    if os.name != "nt":
        import resource
        bound = megabytes * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (bound, bound))
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        return None
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", Counters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    limit = Extended()
    limit.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limit.process_memory = megabytes * 1024 * 1024
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limit), ctypes.sizeof(limit)):
        raise OSError("Cannot establish worker memory limit")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise OSError("Cannot assign worker to limited Job Object")
    return handle  # keep the handle alive through execution


def _worker(payload: dict) -> dict:
    tree = inspect_python(payload["code"], payload["max_chars"])
    job = _memory_limit(payload["memory_mb"])
    namespace = {"__builtins__": ALLOWED_BUILTINS}
    grounding = {}

    def capture(frame, event, arg):
        if frame.f_code.co_name == "solution" and event == "return":
            # Never serialize arbitrary objects or callable attributes.
            for key, value in frame.f_locals.items():
                if type(value) in (int, float, bool, str, dict, list, tuple, type(None)):
                    grounding[key] = value
        return capture

    exec(compile(tree, "<financial-solution>", "exec"), namespace)
    sys.settrace(capture)
    try:
        result = namespace["solution"]()
    finally:
        sys.settrace(None)
    if type(result) not in (int, float, bool, str) or isinstance(result, str) and len(result) > 128:
        raise ValueError("Return a finite scalar answer")
    output = {"success": True, "result": result, "locals": grounding, "error": None,
              "executor": "restricted-cpython-v1", "memory_limit_enforced": True}
    encoded = json.dumps(output, allow_nan=False)
    if len(encoded) > 100000:
        raise ValueError("Execution output exceeds size limit")
    return output


def execute_python(code: str, *, timeout_seconds: float = 3.0, memory_mb: int = 128, max_chars: int = 20000) -> dict:
    try:
        inspect_python(code, max_chars)
        payload = {"code": code, "max_chars": max_chars, "memory_mb": memory_mb}
        # No inherited API keys, user site packages, project modules, or user CWD.
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
        with tempfile.TemporaryDirectory(prefix="financial-worker-") as tmp:
            proc = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker"],
                                  input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                                  env=env, cwd=tmp, timeout=timeout_seconds,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if proc.returncode or not proc.stdout:
            raise ValueError(f"Worker failed (exit {proc.returncode})")
        return json.loads(proc.stdout)
    except (ValueError, SyntaxError, OSError, subprocess.TimeoutExpired, RecursionError) as exc:
        return {"success": False, "result": None, "locals": {}, "error": f"{type(exc).__name__}: {exc}",
                "executor": "restricted-cpython-v1", "memory_limit_enforced": False}


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        output = _worker(json.loads(sys.stdin.read(100000)))
    except Exception as exc:
        output = {"success": False, "result": None, "locals": {}, "error": f"{type(exc).__name__}: {exc}",
                  "executor": "restricted-cpython-v1"}
    print(json.dumps(output, allow_nan=False))

