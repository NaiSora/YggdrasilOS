import io
import sys

from yggdrasil import common


def test_parse_os_release_handles_quotes_and_comments():
    text = '# commentaire\nNAME="Yggdrasil"\nID=yggdrasil\nPRETTY_NAME=\'Yggdrasil 1.0 (Midgard)\'\nBROKEN\n'
    data = common.parse_os_release(text)
    assert data == {"NAME": "Yggdrasil", "ID": "yggdrasil", "PRETTY_NAME": "Yggdrasil 1.0 (Midgard)"}


def test_human_size_and_duration():
    assert common.human_size(512) == "512 o"
    assert common.human_size(2048) == "2.0 Ko"
    assert common.human_size(5 * 1024**3) == "5.0 Go"
    assert common.human_duration(59) == "0 min"
    assert common.human_duration(3 * 86400 + 2 * 3600 + 5 * 60) == "3 j 2 h 5 min"


def test_table_aligns_columns():
    out = common.table([("a", "bb"), ("ccc", "d")], headers=("x", "y"))
    lines = out.splitlines()
    assert lines[0].startswith("x  ")
    assert lines[2].startswith("a    bb")
    assert lines[3].startswith("ccc  d")


def test_deep_merge_keeps_nested_defaults():
    merged = common.deep_merge({"a": {"b": 1, "c": 2}, "d": 3}, {"a": {"c": 9}})
    assert merged == {"a": {"b": 1, "c": 9}, "d": 3}


def test_confirm_refuses_without_terminal(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert common.confirm("Supprimer ?") is False
    assert common.confirm("Supprimer ?", assume_yes=True) is True


def test_runner_dry_run_does_not_execute(capsys):
    runner = common.Runner(dry_run=True)
    proc = runner.run(["rm", "-rf", "/nexistepas"])
    assert proc.returncode == 0
    assert "simulation" in capsys.readouterr().out
    assert runner.log == [["rm", "-rf", "/nexistepas"]]


def test_runner_query_never_raises():
    code, out = common.Runner().query(["commande-qui-n-existe-pas-ygg"])
    assert code == 127 and out == ""


def test_load_config_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "yggdrasil").mkdir()
    (tmp_path / "yggdrasil" / "config.toml").write_text('[mimir]\nmodel = "qwen3:4b"\n', encoding="utf-8")
    cfg = common.load_config()
    assert cfg["mimir"]["model"] == "qwen3:4b"
    assert cfg["mimir"]["host"] == "http://127.0.0.1:11434"
    assert cfg["norns"]["keep"] == 7
