import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app

client = app.test_client()


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_languages_lists_three_languages():
    r = client.get("/api/languages")
    ids = {lang["id"] for lang in r.get_json()["languages"]}
    assert ids == {"python", "c", "cpp"}


def test_samples_endpoint_filters_by_language():
    r = client.get("/api/samples?language=python")
    samples = r.get_json()["samples"]
    assert len(samples) > 0
    assert all(s["language"] == "python" for s in samples)


def test_analyze_python_end_to_end():
    r = client.post("/api/analyze", json={"language": "python", "code": "print('hi')"})
    data = r.get_json()
    assert r.status_code == 200
    assert data["success"] is True
    assert data["execution"]["stdout"].strip() == "hi"
    assert len(data["flowchart"]["nodes"]) > 0


def test_analyze_rejects_missing_code():
    r = client.post("/api/analyze", json={"language": "python", "code": ""})
    assert r.status_code == 400
    assert r.get_json()["success"] is False


def test_analyze_rejects_unsupported_language():
    r = client.post("/api/analyze", json={"language": "rust", "code": "fn main() {}"})
    assert r.status_code == 400


def test_analyze_rejects_non_json_body():
    r = client.post("/api/analyze", data="not json", content_type="text/plain")
    assert r.status_code == 400


def test_analyze_rejects_oversized_code():
    huge = "x = 1\n" * 20000
    r = client.post("/api/analyze", json={"language": "python", "code": huge})
    assert r.status_code == 400


def test_analyze_decouples_execution_and_flowchart_errors():
    # Valid Python that executes fine; flowchart should also succeed here,
    # this test documents the CONTRACT: both fields are always independently present.
    r = client.post("/api/analyze", json={"language": "python", "code": "print(1)"})
    data = r.get_json()
    assert "execution" in data and "flowchart" in data and "flowchartError" in data


def test_execute_only_endpoint_has_no_flowchart_key():
    r = client.post("/api/execute", json={"language": "python", "code": "print(1)"})
    data = r.get_json()
    assert "flowchart" not in data
    assert data["execution"]["stdout"].strip() == "1"


def test_flowchart_only_endpoint_does_not_execute():
    # An infinite loop would hang /api/analyze's execution step, but
    # /api/flowchart must return quickly since it never runs the code.
    import time
    start = time.time()
    r = client.post("/api/flowchart", json={"language": "python", "code": "while True:\n    pass\n"})
    elapsed = time.time() - start
    assert elapsed < 2
    data = r.get_json()
    assert data["success"] is True
    assert len(data["flowchart"]["nodes"]) > 0


def test_c_end_to_end_via_api():
    code = '#include <stdio.h>\nint main(){ printf("Factorial = %d", 120); return 0; }'
    r = client.post("/api/analyze", json={"language": "c", "code": code})
    data = r.get_json()
    assert data["execution"]["stdout"] == "Factorial = 120"
    assert len(data["flowchart"]["nodes"]) > 0


def test_cpp_end_to_end_via_api():
    code = '#include <iostream>\nusing namespace std;\nint main(){ cout << "Prime Number"; return 0; }'
    r = client.post("/api/analyze", json={"language": "cpp", "code": code})
    data = r.get_json()
    assert data["execution"]["stdout"] == "Prime Number"
    assert len(data["flowchart"]["nodes"]) > 0
