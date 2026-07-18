"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-78: OS Command Injection via `shell=True`.
"""

import subprocess


def run_backup(target_dir: str) -> None:
    subprocess.call("tar -czf backup.tar.gz " + target_dir, shell=True)
