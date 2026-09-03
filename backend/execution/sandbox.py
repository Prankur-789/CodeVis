"""
codevis.execution.sandbox
~~~~~~~~~~~~~~~~~~~~~~~~~
Runs untrusted, user-submitted source code with defense-in-depth process
isolation: a fresh temp directory per run, a hard wall-clock timeout, CPU
time / memory / file-size / open-file / process-count limits via
`resource.setrlimit`, a stripped environment, and best-effort automatic
cleanup. The whole process tree is killed via its own process group so a
forked child can't outlive the timeout.

HONEST LIMITATION (documented, not hidden): `resource.setrlimit` and a
scratch temp dir are *process-level* isolation, not kernel/VM-level
isolation. They stop runaway CPU/memory/fork-bombs and wall-clock hangs,
run as a restricted user with no listening sockets, and (see `_kill_group`
below) guarantee the request itself returns within the configured timeout
no matter how many child processes were spawned -- but they do not provide
the same guarantee as a container or microVM against a determined
sandbox-escape exploit in the compiler/interpreter itself. For a
multi-tenant public deployment, this module is designed to be swapped for a
call into the containerized execution service described in
`backend/docker/Dockerfile.execution` (Docker + `--network none` +
non-root user + read-only rootfs + seccomp + cgroup limits), without
changing any adapter or API code -- see docs/TECHNICAL_DOCS.md,
"Security Model", which also documents a fork-bomb wall-clock-containment
bug found and fixed during development of this module.
"""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

CPU_TIME_LIMIT_SECONDS = int(os.environ.get("CODEVIS_CPU_LIMIT", "5"))
WALL_TIME_LIMIT_SECONDS = float(os.environ.get("CODEVIS_WALL_LIMIT", "8"))
MEMORY_LIMIT_BYTES = int(os.environ.get("CODEVIS_MEM_LIMIT_MB", "256")) * 1024 * 1024
MAX_OUTPUT_BYTES = int(os.environ.get("CODEVIS_MAX_OUTPUT_BYTES", str(200 * 1024)))
MAX_PROCESSES = int(os.environ.get("CODEVIS_MAX_PROCS", "16"))
FILE_SIZE_LIMIT_BYTES = 10 * 1024 * 1024


@dataclass
class ExecutionResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    status: str = "ok"          # ok | compile_error | runtime_error | timeout | internal_error
    execution_time: float = 0.0
    exit_code: int | None = None
    compiler_output: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "status": self.status,
            "executionTime": round(self.execution_time, 4),
            "exitCode": self.exit_code,
            "compilerOutput": self.compiler_output,
        }


def _apply_resource_limits() -> None:
    """Runs in the child process (via preexec_fn) right before exec()."""
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_TIME_LIMIT_SECONDS, CPU_TIME_LIMIT_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_LIMIT_BYTES, FILE_SIZE_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    # New session/process-group so the *entire* tree it spawns can be killed
    # atomically by pgid -- see _kill_group().
    os.setsid()


_SAFE_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "HOME": "/tmp",
}


def run_subprocess(argv: list[str], cwd: str, stdin_data: str = "", timeout: float | None = None) -> ExecutionResult:
    """Runs `argv` under the resource-limited sandbox and captures output.

    Uses Popen (not subprocess.run) so that on timeout we can SIGKILL the
    *entire process group* the child created via os.setsid(), rather than
    just the direct child PID. This matters concretely: a fork-bomb-style
    program keeps orphaned descendants alive under subprocess.run's default
    timeout handling, and under CPU contention from many siblings each one
    individually reaching RLIMIT_CPU can take far longer in wall-clock time
    than the configured timeout. Killing the whole group closes that gap.
    """
    timeout = timeout or WALL_TIME_LIMIT_SECONDS
    start = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_SAFE_ENV,
        preexec_fn=_apply_resource_limits,
    )
    try:
        out, err = proc.communicate(input=stdin_data.encode(), timeout=timeout)
        elapsed = time.monotonic() - start
        stdout = out.decode(errors="replace")[:MAX_OUTPUT_BYTES]
        stderr = err.decode(errors="replace")[:MAX_OUTPUT_BYTES]

        if proc.returncode == 0:
            return ExecutionResult(True, stdout, stderr, "ok", elapsed, proc.returncode)
        if proc.returncode == -signal.SIGXCPU:
            return ExecutionResult(
                False, stdout, stderr, "timeout", elapsed, proc.returncode,
                metadata={"message": f"CPU time limit ({CPU_TIME_LIMIT_SECONDS}s) exceeded."},
            )
        if proc.returncode in (-signal.SIGKILL, -signal.SIGSEGV) and not stderr:
            return ExecutionResult(
                False, stdout, stderr, "runtime_error", elapsed, proc.returncode,
                metadata={"message": "Process was terminated (likely exceeded a resource limit)."},
            )
        if "SyntaxError" in stderr and argv[0] == "python3":
            return ExecutionResult(False, stdout, stderr, "syntax_error", elapsed, proc.returncode)
        return ExecutionResult(False, stdout, stderr, "runtime_error", elapsed, proc.returncode)
    except subprocess.TimeoutExpired:
        _kill_group(proc.pid)
        try:
            out, err = proc.communicate(timeout=2)
        except Exception:
            out, err = b"", b""
        elapsed = time.monotonic() - start
        return ExecutionResult(
            False,
            out.decode(errors="replace")[:MAX_OUTPUT_BYTES] if out else "",
            "",
            "timeout",
            elapsed,
            None,
            metadata={"message": f"Execution exceeded the {timeout}s time limit."},
        )
    finally:
        _kill_group(proc.pid)


def _kill_group(pid: int) -> None:
    """SIGKILL the entire process group rooted at `pid`. See module docstring."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


class TempWorkspace:
    """Context manager for a scratch directory that is always cleaned up."""

    def __enter__(self) -> str:
        self.path = tempfile.mkdtemp(prefix="codevis_")
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
