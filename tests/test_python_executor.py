import pytest

from financial_annotation_harness.python_executor import execute_python


@pytest.mark.parametrize("code,expected", [
    ("def solution():\n    revenue = 125\n    return revenue", 125),
    ("def solution():\n    amounts = {2023: 7, 2024: 9}\n    winner = max(amounts, key=amounts.get)\n    return winner", 2024),
    ("def solution():\n    values = [3, 2, 1]\n    declines = all(a > b for a,b in zip(values, values[1:]))\n    return 'Yes' if declines else 'No'", "Yes"),
    ("def solution():\n    values = {2023: 30, 2024: 20}\n    ratios = {y: values[y] / 100 for y in values}\n    return sum(ratios.values())", 0.5),
])
def test_supported_python(code, expected):
    result = execute_python(code)
    assert result["success"], result
    assert result["memory_limit_enforced"]
    assert result["result"] == expected


@pytest.mark.parametrize("code", [
    "import os\ndef solution():\n    return 1",
    "def solution():\n    return open('secret').read()",
    "def solution():\n    return (1).__class__",
    "def solution():\n    return eval('1')",
    "def solution():\n    return solution()",
    "def solution():\n    while True:\n        pass\n    return 1",
    "def solution():\n    return 2 ** 100000000",
    "def solution():\n    return __import__('os')",
    "def solution(x=1):\n    return x",
    "def solution():\n    max = abs\n    return max(-1)",
    "def solution():\n    return 1e999",
    "def solution():\n    return [1, 2]",
    "def solution():\n    return 1 / 0",
])
def test_rejects_unsafe_or_invalid_python(code):
    assert not execute_python(code)["success"]


def test_timeout_and_memory_exhaustion():
    result = execute_python("def solution():\n    amount = 1\n    return amount", timeout_seconds=0.0001)
    assert not result["success"]
    huge = execute_python("def solution():\n    text = 'a' * 1000000000\n    return len(text)")
    assert not huge["success"]

