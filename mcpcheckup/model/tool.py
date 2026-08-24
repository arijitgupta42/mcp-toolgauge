"""The shared vocabulary: what mcpcheckup knows about a server and its tools.

Everything downstream -- lint rules, eval cases, reports -- consumes these models rather
than the MCP SDK's own protocol types. That indirection is deliberate. The SDK's `Tool` is
a wire format that tracks the spec; ours is a stable analysis surface. Pinning every rule
in the codebase to a third-party model would turn each SDK release into a breaking change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from inspect import cleandoc
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolAnnotations(BaseModel):
    """Behavioural hints a server declares about a tool.

    Every field is optional and tri-state: `None` means the server said nothing, which is a
    different (and lintable) condition from explicitly saying `False`.
    """

    model_config = ConfigDict(frozen=True)

    title: str | None = None
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None


class ToolSpec(BaseModel):
    """One tool as advertised by a server -- the unit every lint rule operates on."""

    model_config = ConfigDict(frozen=True)

    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    annotations: ToolAnnotations | None = None

    @field_validator("title", "description", mode="after")
    @classmethod
    def _normalise_text(cls, value: str | None) -> str | None:
        """Strip docstring indentation, and treat blank as absent.

        Most servers derive descriptions from docstrings, and how much leading whitespace
        survives depends on the *server author's* Python version: 3.13 dedents docstrings
        at compile time, 3.11 and 3.12 do not. Left alone, that would silently change
        description length, similarity scores, and the text we put in eval prompts,
        depending on an interpreter we do not control. `cleandoc` is exactly the
        transformation 3.13 applies, so applying it everywhere makes the analysis surface
        the same on every version.

        Empty and whitespace-only descriptions collapse to None: a server that sends `""`
        and one that omits the field have the same defect, and rules should not have to
        check for both.
        """
        if value is None:
            return None
        # cleandoc fixes indentation but leaves trailing whitespace on a single line, and
        # leaves a whitespace-only string non-empty; strip picks up both.
        return cleandoc(value).strip() or None

    @property
    def parameters(self) -> dict[str, Any]:
        """The tool's parameter subschemas, keyed by parameter name."""
        properties = self.input_schema.get("properties", {})
        return properties if isinstance(properties, dict) else {}

    @property
    def required_parameters(self) -> tuple[str, ...]:
        """Names of parameters the schema marks as required."""
        required = self.input_schema.get("required", [])
        if not isinstance(required, list):
            return ()
        return tuple(str(name) for name in required)


class ServerInfo(BaseModel):
    """Identity a server reports during initialization."""

    model_config = ConfigDict(frozen=True)

    name: str | None = None
    version: str | None = None
    protocol_version: str | None = None
    instructions: str | None = None


class InspectResult(BaseModel):
    """The full read-only snapshot of a server: who it says it is, and what it offers.

    `target` records how we reached the server, so a report is reproducible from its own
    contents rather than from the shell history that produced it.
    """

    model_config = ConfigDict(frozen=True)

    target: str
    server: ServerInfo
    tools: tuple[ToolSpec, ...] = ()

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)


def canonical_json(model: BaseModel, *, indent: int | None = 2) -> str:
    """Serialise a model deterministically: sorted keys, no incidental whitespace.

    Determinism is the point. It makes the `--json` renderer golden-file testable today,
    and it is what a content-addressed eval cache key will be built from later -- the same
    tools must always produce the same bytes.
    """
    payload = model.model_dump(mode="json", exclude_none=True)
    separators = (",", ": ") if indent is not None else (",", ":")
    return json.dumps(payload, sort_keys=True, indent=indent, separators=separators)


# Long enough that a collision is not a thing that happens, short enough to read in a diff
# and to paste into an issue.
DIGEST_LENGTH = 16


def tool_digest(tools: Iterable[ToolSpec]) -> str:
    """A stable fingerprint of a server's whole tool surface.

    Two things depend on this. Eval cases record the digest they were written against, so a
    run can say "these cases predate your current tools, the scores are not comparable".
    And it is part of the eval cache key, so editing a description invalidates exactly the
    cached answers that description could have changed -- which is what you want, because
    that edit is the thing you are trying to measure.

    Order-insensitive by construction: the digest answers "is this the same tool surface?",
    and a server that registers the same tools in a different order has the same surface.
    Registration order is an implementation detail of the server's source file, and making
    a reshuffle silently discard a paid-for cache would be a bad trade.
    """
    payload = "\n".join(sorted(canonical_json(tool, indent=None) for tool in tools))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]
