import pytest
from codegen.schema.runnable_contract import parse_runnable_contract, RunnableContract


def _valid():
    return {
        "kind": "spa",
        "build": "pnpm -r build",
        "start": "serve dist on $PORT",
        "liveness": "HTTP 200 at /",
        "primary_surface": {"req": "FR-001", "assert": "catalog renders >=1 row"},
        "surfaces": [{"req": "FR-006", "assert": "phase graph renders"}],
    }


@pytest.mark.unit
def test_valid_contract_parses_and_derives_probe():
    c = parse_runnable_contract(_valid())
    assert isinstance(c, RunnableContract)
    assert c.kind == "spa"
    assert c.probe == "browser"            # derived from kind
    assert c.primary_surface["req"] == "FR-001"


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["build", "liveness", "primary_surface"])
def test_missing_mandatory_field_raises(missing):
    data = _valid()
    del data[missing]
    with pytest.raises(ValueError, match=missing):
        parse_runnable_contract(data)


@pytest.mark.unit
def test_unknown_kind_raises():
    data = _valid()
    data["kind"] = "wasm-blob"
    with pytest.raises(ValueError, match="kind"):
        parse_runnable_contract(data)


@pytest.mark.unit
def test_primary_surface_requires_req_and_assert():
    data = _valid()
    data["primary_surface"] = {"assert": "x"}   # missing req
    with pytest.raises(ValueError, match="primary_surface"):
        parse_runnable_contract(data)


@pytest.mark.unit
def test_cli_kind_allows_null_start_and_exec_probe():
    data = _valid()
    data["kind"] = "cli"
    data["start"] = None
    c = parse_runnable_contract(data)
    assert c.start is None
    assert c.probe == "exec"


@pytest.mark.unit
def test_re_phase_documents_a_parseable_example_contract():
    """The RE phase spec must contain a runnable_contract example that parses,
    so authors copy a valid shape."""
    import re as _re, pathlib, yaml
    spec = pathlib.Path("runtime/workflow/phases/codegen-1-re.md").read_text()
    m = _re.search(r"```yaml\n(runnable_contract:.*?)\n```", spec, _re.S)
    assert m, "codegen-1-re.md must contain a ```yaml runnable_contract: ...``` example"
    data = yaml.safe_load(m.group(1))["runnable_contract"]
    parse_runnable_contract(data)        # must not raise
