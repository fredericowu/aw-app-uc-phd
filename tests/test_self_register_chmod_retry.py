from uc_phd_app.mcp import self_register


def test_register_self_unchanged_entry_survives_chmod_failure(tmp_path, monkeypatch):
    self_register.register_self(str(tmp_path), 9482)
    path = tmp_path / "mcp.json"
    original = path.read_bytes()
    attempts = []

    def denied(filename, mode):
        attempts.append((filename, mode))
        raise PermissionError("chmod denied")

    with monkeypatch.context() as patch:
        patch.setattr(self_register.os, "chmod", denied)
        self_register.register_self(str(tmp_path), 9482)

    assert attempts == [(str(path), 0o600)]
    assert path.read_bytes() == original
