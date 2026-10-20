from netshift.store import History, PresetStore, Settings, summarize


def test_default_presets_created(tmp_path):
    s = PresetStore(tmp_path)
    assert len(s.presets) >= 1
    assert (tmp_path / "presets.json").exists()


def test_add_update_delete_unique_names(tmp_path):
    s = PresetStore(tmp_path)
    s.presets = []
    a = s.add("Lab", {"mode": "static", "ip": "10.0.0.1", "mask": "24"})
    b = s.add("Lab", {"mode": "dhcp"})
    assert b["name"] == "Lab (2)"
    s.update(a["id"], description="bench")
    assert PresetStore(tmp_path).get(a["id"])["description"] == "bench"
    s.delete(b["id"])
    assert [p["name"] for p in PresetStore(tmp_path).presets] == ["Lab"]


def test_export_import(tmp_path):
    s = PresetStore(tmp_path)
    out = tmp_path / "export.json"
    s.export(str(out))
    (tmp_path / "other").mkdir()
    other = PresetStore(tmp_path / "other")
    before = len(other.presets)
    assert other.import_file(str(out)) == len(s.presets)
    assert len(other.presets) == before + len(s.presets)


def test_history_last_for(tmp_path):
    h = History(tmp_path)
    h.add("Eth", "NIC A", {"mode": "dhcp"}, {"mode": "static"}, "test", True)
    h.add("Eth2", "NIC B", {"mode": "dhcp"}, {"mode": "dhcp"}, "test", True)
    assert History(tmp_path).last_for("NIC A")["adapter"] == "Eth"


def test_settings_persist(tmp_path):
    Settings(tmp_path).set("theme", "light")
    assert Settings(tmp_path).get("theme") == "light"


def test_summarize():
    assert summarize({"mode": "dhcp"}) == "DHCP"
    assert summarize({"mode": "static", "ip": "10.0.0.5", "mask": "255.255.255.0", "gateway": "10.0.0.1"}) \
        == "10.0.0.5/24 · GW 10.0.0.1"
