from cogs.annonces import parse_flux_youtube

FLUX = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>abc123</yt:videoId>
    <title>Une vidéo</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
  </entry>
  <entry>
    <yt:videoId>def456</yt:videoId>
    <title>La précédente</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=def456"/>
  </entry>
</feed>"""


def test_flux_youtube():
    assert parse_flux_youtube(FLUX) == [
        ("abc123", "Une vidéo", "https://www.youtube.com/watch?v=abc123"),
        ("def456", "La précédente", "https://www.youtube.com/watch?v=def456"),
    ]
