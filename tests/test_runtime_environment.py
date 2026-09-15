from financial_annotation_harness import runtime_environment as env


def test_unknown_hardware_not_invented(monkeypatch):
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    monkeypatch.setattr(env, "command_output", lambda cmd: None)
    monkeypatch.setattr(env, "windows_memory_bytes", lambda: None)
    monkeypatch.setattr(env.shutil, "which", lambda name: None)
    result = env.environment_snapshot()
    assert result["ram_bytes"] is None and result["gpus"] == []


def test_hardware_units(monkeypatch):
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    monkeypatch.setattr(env.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(env, "windows_memory_bytes", lambda: 34359738368)
    monkeypatch.setattr(env, "command_output", lambda cmd: '{"TotalPhysicalMemory": 34359738368}' if cmd[0] == "powershell.exe" else "Fixture GPU, 16384, 999.0")
    result = env.environment_snapshot()
    assert result["ram_bytes"] == 34359738368 and result["gpus"][0]["vram_mib"] == 16384
