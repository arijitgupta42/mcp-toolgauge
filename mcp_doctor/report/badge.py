"""The shields.io endpoint badge.

shields.io renders a badge from a tiny JSON document served at a URL you control -- commit
this file, host it (a raw GitHub URL is enough), and point
`https://img.shields.io/endpoint?url=<raw url>` at it. The badge is the distribution
mechanism: every README that carries one advertises the tool to everyone who visits that
repo, so the one number it shows is the health score and nothing else. What "lint-only" versus
"lint + eval" means is a distinction for the report and the JSON, not for a badge that has to
read at a glance.
"""

from __future__ import annotations

import json

from mcp_doctor.health import color_for
from mcp_doctor.model import HealthScore

# The badge's left-hand label. A fixed name rather than the server's, so the badge says what
# measured it -- the server's own name is already the repo the badge sits in.
BADGE_LABEL = "mcp-doctor"


def render_badge(health: HealthScore, *, label: str = BADGE_LABEL) -> str:
    """The shields.io endpoint document for a health score. Sorted keys, so it is diffable."""
    document = {
        "schemaVersion": 1,
        "label": label,
        "message": str(health.overall),
        "color": color_for(health.overall),
    }
    return json.dumps(document, indent=2, sort_keys=True)
