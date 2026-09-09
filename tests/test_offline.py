"""The judged run has networking disabled, so the bundle must not reach for anything."""

import re
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parents[1] / "frontend/dist"

# Namespace identifiers and attribution links are declarations, not fetches.
ALLOWED = re.compile(r"https?://(www\.)?(w3\.org|maplibre\.org|github\.com)/")
# Anything the browser would load: a stylesheet url(), a src/href asset, an import.
FETCHES = re.compile(r"""(?:url\(|src=|href=|import\s*\(\s*)["']?(https?://[^"')\s]+)""")

pytestmark = pytest.mark.skipif(not DIST.is_dir(), reason="frontend not built")


@pytest.mark.parametrize("suffix", [".html", ".js", ".css"])
def test_bundle_fetches_nothing_from_the_network(suffix):
    offenders = []
    for path in DIST.rglob(f"*{suffix}"):
        for url in FETCHES.findall(path.read_text(encoding="utf-8", errors="replace")):
            if not ALLOWED.match(url):
                offenders.append(f"{path.relative_to(DIST)}: {url}")
    assert not offenders, "bundle would fetch from the network: " + "; ".join(offenders)


def test_map_style_carries_no_remote_tiles_glyphs_or_sprites():
    """An empty style keeps MapLibre from requesting a basemap it cannot reach."""
    source = (Path(__file__).resolve().parents[1] / "frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "style: { version: 8, sources: {}, layers: [] }" in source
    for key in ("glyphs", "sprite", "tiles"):
        assert f"{key}:" not in source
