#!/usr/bin/env python3
"""RT-lint (VS-01, ARCHITECTURE 4.2 rule 1): the real-time path never allocates, locks,
makes a syscall, sleeps, reads a clock or logs.

    scripts/rt-lint.py [ROOT]     check ROOT/src/engine/render, ROOT/src/engine/dsp and
                                  ROOT/src/host/rt (the audio callback's work, VS-13)

Comments and string literals are ignored; every other mention of a forbidden name, or an
include of a forbidden header, is a failure with file:line and the reason. A function
that genuinely must be called from those directories and is not real-time unsafe is
exempted by name in ALLOW below, with the reason, so the exemption is reviewable.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DIRS = ("src/engine/render", "src/engine/dsp", "src/host/rt")

FORBIDDEN = {
    "allocation": "malloc calloc realloc free aligned_alloc posix_memalign valloc strdup "
    "strndup alloca mmap munmap brk sbrk new delete",
    "locks": "pthread_mutex_lock pthread_mutex_unlock pthread_mutex_trylock pthread_mutex_init "
    "pthread_cond_wait pthread_cond_signal pthread_cond_broadcast pthread_cond_timedwait "
    "pthread_rwlock_rdlock pthread_rwlock_wrlock pthread_spin_lock sem_wait sem_post "
    "sem_timedwait mtx_lock mtx_unlock cnd_wait os_unfair_lock_lock dispatch_sync",
    "syscalls and I/O": "open close read write fopen fclose fread fwrite fflush fseek "
    "ioctl poll select epoll_wait socket send recv sendto recvfrom fork exec system "
    "kill raise signal sigaction",
    "sleep and clocks": "sleep usleep nanosleep clock_nanosleep sched_yield thrd_sleep "
    "clock_gettime gettimeofday time mach_absolute_time",
    "logging and printing": "printf fprintf vprintf vfprintf puts fputs putchar fputc "
    "syslog perror sim_printf",
}

FORBIDDEN_HEADERS = {
    "stdio.h": "logging and I/O",
    "pthread.h": "locks",
    "threads.h": "locks",
    "semaphore.h": "locks",
    "unistd.h": "syscalls",
    "fcntl.h": "syscalls",
    "sys/mman.h": "allocation",
    "time.h": "clocks",
    "syslog.h": "logging",
}

ALLOW: dict[str, str] = {}

STRIP = re.compile(r"/\*.*?\*/|//[^\n]*|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'", re.S)


def blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def lint_file(path: Path, rel: str) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r'\s*#\s*include\s*[<"]([^>"]+)[>"]', line)
        if m and m.group(1) in FORBIDDEN_HEADERS:
            problems.append(
                f"{rel}:{n}: includes <{m.group(1)}> ({FORBIDDEN_HEADERS[m.group(1)]}); "
                f"the render path may not use it"
            )
    code = STRIP.sub(blank, text)
    for n, line in enumerate(code.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for why, names in FORBIDDEN.items():
            for name in names.split():
                if name in ALLOW:
                    continue
                if re.search(rf"(?<![\w.>]){re.escape(name)}\s*\(", line):
                    problems.append(
                        f"{rel}:{n}: calls {name}() ({why}). Real-time code may not; do it "
                        f"on a control thread and pass the result through the command ring"
                    )
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else Path(__file__).resolve().parents[1])
    problems, files = [], 0
    for d in DIRS:
        for p in sorted((root / d).rglob("*")):
            if p.suffix in (".c", ".h"):
                files += 1
                problems += lint_file(p, str(p.relative_to(root)))
    if problems:
        print(f"RT-lint FAILED: {len(problems)} problem(s) in {files} file(s)")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print(f"RT-lint passed: {files} file(s) under {', '.join(DIRS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
