"""Render a saved Friendly Filter JSON export without importing the backend."""

import json
from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m interop_consumer EXPORT.json", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if path.stat().st_size > 4_194_304:
        print("export is too large", file=sys.stderr)
        return 2
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0" or not isinstance(document.get("tracks"), list):
        print("unsupported export", file=sys.stderr)
        return 2
    print("track_id\tcategory\tstale\texplanation")
    for track in document["tracks"]:
        required = (track.get("track_id"), track.get("category"), track.get("is_stale"),
                    track.get("explanation"))
        if not required[0] or not required[1] or not isinstance(required[2], bool) or not required[3]:
            print("invalid track", file=sys.stderr)
            return 2
        marker = "!" if track["category"] == "LIKELY_RED" else " "
        print(f"{marker}{track['track_id']}\t{track['category']}\t{track['is_stale']}\t{track['explanation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
