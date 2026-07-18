"""A deliberately clean, authored example for the golden benchmark dataset.

A genuinely inert utility with no security-relevant constructs at all (no
subprocess, network, crypto, or deserialization calls) — even a bare
`import subprocess` trips Bandit's low-severity B404 heads-up regardless of
how it's used, so this is a true negative that doesn't import it in the
first place, rather than one that merely uses it "safely."
Expected findings: none.
"""


def total_backup_size(file_sizes: list[int]) -> int:
    return sum(size for size in file_sizes if size > 0)
