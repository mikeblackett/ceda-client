from ceda_client.converter import converter
from ceda_client.client import Result, ResultBatch, Status
from ceda_client.schema import File


def _file(name="x.nc"):
    return converter.structure(
        {
            "path": f"/x/{name}",
            "name": name,
            "type": "file",
            "location": ["on_disk"],
            "md5": "a" * 32,
            "size": 1,
            "download": "https://example.com/x.nc",
            "last_modified": None,
        },
        File,
    )


def test_result_constructors():
    file = _file()
    s = Result.succeed(file, "p1")
    k = Result.skip(file, "p2")
    e = OSError("boom")
    f = Result.fail(file, "p3", e)
    assert s.status is Status.SUCCESS and s.error is None
    assert k.status is Status.SKIPPED and k.error is None
    assert f.status is Status.FAILED and f.error is e


def test_result_batch_counters_and_lists():
    file = _file()
    results = (
        Result.succeed(file, "p1"),
        Result.skip(file, "p2"),
        Result.fail(file, "p3", OSError("x")),
        Result.fail(file, "p4", OSError("y")),
    )
    batch = ResultBatch(results)
    assert batch.counter[Status.SUCCESS] == 1
    assert batch.counter[Status.SKIPPED] == 1
    assert batch.counter[Status.FAILED] == 2
    assert [r.path for r in batch.success] == ["p1"]
    assert [r.path for r in batch.skipped] == ["p2"]
    assert [r.path for r in batch.failed] == ["p3", "p4"]


def test_result_batch_empty():
    batch = ResultBatch(())
    assert batch.counter == {}
    assert batch.success == batch.failed == batch.skipped == []
