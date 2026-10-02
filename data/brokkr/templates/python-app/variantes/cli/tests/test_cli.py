from {{snake}}.cli import main


def test_cli_reads_file(tmp_path, capsys):
    sample = tmp_path / "texte.txt"
    sample.write_text("un deux deux", encoding="utf-8")
    assert main([str(sample), "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "3 mots" in out and "deux" in out
