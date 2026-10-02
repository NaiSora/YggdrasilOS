from {{snake}}.core import word_stats


def test_word_stats_counts_and_ranks():
    stats = word_stats("Le chêne et le frêne.\nLe chêne !", top=2)
    assert stats.lines == 2
    assert stats.words == 7
    assert stats.most_common == [("le", 3), ("chêne", 2)]
