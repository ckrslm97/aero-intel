"""Topic pipelines.

Each module here owns one subject: its sources, its gate, its validation rules
and the fields a record needs before it can be published. The shared machinery
-- fetching, language gating, clustering, confidence scoring, persistence --
lives in the runner and is identical for every topic.

See base.py for the contract and why this is a set of declared pipelines rather
than models that search the web at runtime.
"""
from app.agents.base import GateResult, SourceSpec, TopicAgent

__all__ = ["GateResult", "SourceSpec", "TopicAgent"]
