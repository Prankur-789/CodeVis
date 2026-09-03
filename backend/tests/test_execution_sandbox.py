import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.runners import run_python, run_c, run_cpp


def test_python_success():
    r = run_python("print(2 + 2)")
    assert r.success
    assert r.stdout.strip() == "4"
    assert r.status == "ok"


def test_python_runtime_error():
    r = run_python("x = 1 / 0")
    assert not r.success
    assert r.status in ("runtime_error", "syntax_error")
    assert "ZeroDivisionError" in r.stderr


def test_python_syntax_error_classified_separately():
    r = run_python("if True\n    print(1)")
    assert not r.success
    assert r.status == "syntax_error"


def test_python_reads_stdin():
    r = run_python("name = input()\nprint('hello ' + name)", stdin_data="world\n")
    assert r.success
    assert r.stdout.strip() == "hello world"


def test_python_cpu_limit_enforced():
    r = run_python("x = 0\nwhile True:\n    x += 1")
    assert not r.success
    assert r.status == "timeout"
    assert r.execution_time < 7  # bounded well below the 8s wall-clock ceiling


def test_c_compiles_and_runs():
    code = '#include <stdio.h>\nint main(){ printf("Factorial = %d", 120); return 0; }'
    r = run_c(code)
    assert r.success
    assert r.stdout == "Factorial = 120"


def test_c_compile_error_reported_separately_from_runtime():
    r = run_c("int main() { int x = ; return 0; }")
    assert not r.success
    assert r.status == "compile_error"
    assert r.compiler_output  # actual gcc diagnostic text is preserved


def test_c_runtime_crash():
    code = "int main() { int *p = 0; *p = 1; return 0; }"
    r = run_c(code)
    assert not r.success
    assert r.status == "runtime_error"


def test_cpp_compiles_and_runs():
    code = '#include <iostream>\nusing namespace std;\nint main(){ cout << "Prime Number"; return 0; }'
    r = run_cpp(code)
    assert r.success
    assert r.stdout == "Prime Number"


def test_cpp_compile_error():
    r = run_cpp("int main() { std::cout << ; return 0; }")
    assert not r.success
    assert r.status == "compile_error"


def test_execution_result_serializes_cleanly():
    import json
    r = run_python("print(1)")
    json.dumps(r.to_dict())


def test_bounded_multi_process_program_still_bounded_by_wall_clock():
    """
    Regression test for a real bug found during development: a program that
    forks several children which outlive the parent must not make the whole
    request take longer than the wall-clock timeout. See sandbox.py's
    `_kill_group` docstring for the full story.
    """
    code = """
#include <unistd.h>
int main() {
    for (int i = 0; i < 3; i++) {
        if (fork() == 0) { sleep(30); return 0; }
    }
    sleep(30);
    return 0;
}
"""
    r = run_c(code)
    assert r.status == "timeout"
    assert r.execution_time < 10  # must not take anywhere near 30s
