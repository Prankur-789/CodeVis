"""
codevis.execution.runners
~~~~~~~~~~~~~~~~~~~~~~~~~
Language-specific "compile (if needed) + run" logic, each isolated inside a
fresh TempWorkspace and executed through the resource-limited sandbox.
"""

from __future__ import annotations

import os
import time

from .sandbox import (
     ExecutionResult,
     TempWorkspace,
     run_subprocess,
     COMPILE_MAX_PROCESSES,
     COMPILE_MEMORY_LIMIT_BYTES,
)

COMPILE_TIMEOUT_SECONDS = 10


def run_python(code: str, stdin_data: str = "") -> ExecutionResult:
    with TempWorkspace() as workdir:
        src_path = os.path.join(workdir, "main.py")
        with open(src_path, "w") as f:
            f.write(code)
        # -I: isolated mode (ignore PYTHONPATH/user site, close to a real sandbox)
        # -B: don't write .pyc files into the scratch dir
        return run_subprocess(["python3", "-I", "-B", "main.py"], cwd=workdir, stdin_data=stdin_data)


def run_c(code: str, stdin_data: str = "") -> ExecutionResult:
    return _compile_and_run(code, "main.c", ["gcc", "-O2", "-std=c11", "-Wall", "main.c", "-o", "main", "-lm"], stdin_data)


def run_cpp(code: str, stdin_data: str = "") -> ExecutionResult:
    return _compile_and_run(
        code, "main.cpp", ["g++", "-O2", "-std=c++17", "-Wall", "main.cpp", "-o", "main"], stdin_data
    )


def _compile_and_run(code: str, filename: str, compile_argv: list[str], stdin_data: str) -> ExecutionResult:
    with TempWorkspace() as workdir:
        src_path = os.path.join(workdir, filename)
        with open(src_path, "w") as f:
            f.write(code)

        start = time.monotonic()
        compile_result = run_subprocess(
            compile_argv,
            cwd=workdir,
            timeout=COMPILE_TIMEOUT_SECONDS,
            max_processes=None,
            memory_limit_bytes=COMPILE_MEMORY_LIMIT_BYTES,
        )
        if compile_result.status == "timeout":
            return ExecutionResult(
                False, "", "", "timeout", time.monotonic() - start,
                metadata={"message": "Compilation exceeded the time limit."},
            )
        if not compile_result.success:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=compile_result.stderr,
                status="compile_error",
                execution_time=time.monotonic() - start,
                compiler_output=compile_result.stderr,
            )

        binary_path = os.path.join(workdir, "main")
        if not os.path.exists(binary_path):
            return ExecutionResult(False, "", "Compiler did not produce an executable.", "compile_error")

        run_result = run_subprocess([binary_path], cwd=workdir, stdin_data=stdin_data)
        run_result.compiler_output = compile_result.stderr  # keep warnings even on success
        return run_result


RUNNERS = {
    "python": run_python,
    "c": run_c,
    "cpp": run_cpp,
}
