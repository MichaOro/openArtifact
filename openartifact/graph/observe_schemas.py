"""Request and response models of the observe mode API (ADR-088)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObserveSetting(BaseModel):
    """The observe mode of a pipeline as it is stored in a draft or a published version."""

    enabled: bool
    days: int | None = Field(
        default=None, description="Observe for this many days (1 to 365); none: no limit in days."
    )
    runs: int | None = Field(
        default=None, description="Observe this many runs (1 to 100000); none: no limit in runs."
    )


class ObserveSet(_Strict):
    """Set the observe mode in the draft; it goes live with the next publication (``publish`` does that in the same call)."""

    enabled: bool
    days: int | None = None
    runs: int | None = None
    publish: bool = Field(
        default=False,
        description="Also publish: refused (409) when the draft has other unpublished changes, so only the mode goes live.",
    )


class ObserveAgain(_Strict):
    """Observe again from now, with a new limit (none given: the published setting's)."""

    days: int | None = None
    runs: int | None = None


class ObserveEvent(BaseModel):
    at: str
    action: Literal["on", "off", "release", "again"]
    by: str
    note: str = ""


class ObserveState(BaseModel):
    """Where the observation of a pipeline stands (the published setting at work)."""

    enabled: bool = Field(description="The published version has the mode on.")
    observing: bool = Field(description="Runs are observed now.")
    ended: bool = Field(
        description="The limit is reached: starts are refused until someone releases or observes again."
    )
    released: bool = Field(
        description="The owner released the pipeline: it runs for real until a publication changes the mode."
    )
    days: int | None
    runs: int | None
    runs_done: int
    started_at: str | None
    ends_at: str | None
    reason: str | None = Field(description="Why starts are refused, when ``ended``.")
    events: list[ObserveEvent]


class ObserveRead(BaseModel):
    pipeline_id: str
    pipeline_name: str
    draft: ObserveSetting | None = Field(
        description="What the draft says (the editor shows this); none: not set."
    )
    published: ObserveSetting | None = Field(
        description="What the version that runs says; none: off."
    )
    draft_differs: bool = Field(description="Publishing now would change the mode.")
    state: ObserveState
