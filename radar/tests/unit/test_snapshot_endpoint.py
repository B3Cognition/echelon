def test_snapshot_status_200(mock_app):
    r = mock_app.get("/snapshot")
    assert r.status_code == 200

def test_snapshot_has_required_keys(mock_app):
    r = mock_app.get("/snapshot")
    data = r.get_json()
    assert "run_id" in data
    assert "agents" in data
    assert "dispatch_order" in data
    assert "updated_at" in data

def test_snapshot_agents_is_dict(mock_app):
    r = mock_app.get("/snapshot")
    data = r.get_json()
    assert isinstance(data["agents"], dict)

def test_snapshot_dispatch_order_is_list(mock_app):
    r = mock_app.get("/snapshot")
    data = r.get_json()
    assert isinstance(data["dispatch_order"], list)

def test_snapshot_agent_entry_has_required_fields(mock_app):
    r = mock_app.get("/snapshot")
    data = r.get_json()
    # Pick the first agent entry and verify its inner fields
    first_agent = next(iter(data["agents"].values()))
    assert "id" in first_agent          # NOT dispatch_id — inner field is "id"
    assert "codename" in first_agent
    assert "display_name" in first_agent
    assert "state" in first_agent
    assert "phase" in first_agent


def test_snapshot_has_run_key(mock_app):
    r = mock_app.get("/snapshot")
    data = r.get_json()
    assert "run" in data
    assert isinstance(data["run"], dict)
    assert "run_id" in data["run"]
    assert "status" in data["run"]
    assert "phase" in data["run"]
