"""Audit report: duplicates, style deviation and caller-supplied signals, in one document.

This is deliberately a *composition*, not a judgement.  The similarity pass comes from
:mod:`cf.similarity`, the style deviation from :mod:`cf.consistency` against a stored profile,
and any other signal arrives already computed: :func:`collect_signals` merges it by submission id
or path and never interprets it.  ``flags`` is a list of reasons for a human to look at, and
nothing here concludes misconduct.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .consistency import analyze
from .document import build_document
from .similarity import (ProgressEvent, SimilarityError, SimilarityReport, Submission,
                         find_duplicates, read_document)
from .store import ProfileStore

SCHEMA_VERSION = 1
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class StyleDeviation:
    id: str
    user: str
    findings: int
    max_severity: str | None
    rules: tuple

    def to_dict(self) -> dict:
        return {"id": self.id, "user": self.user, "findings": self.findings,
                "max_severity": self.max_severity, "rules": list(self.rules)}


@dataclass(frozen=True)
class Flag:
    id: str
    reasons: tuple

    def to_dict(self) -> dict:
        return {"id": self.id, "reasons": list(self.reasons)}


@dataclass
class AuditReport:
    version: int = SCHEMA_VERSION
    duplicates: SimilarityReport | None = None
    style_deviations: list = field(default_factory=list)
    external_signals: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "duplicates": self.duplicates.to_dict() if self.duplicates else {},
            "style_deviations": [s.to_dict() for s in sorted(self.style_deviations, key=lambda x: x.id)],
            "external_signals": [dict(s) for s in sorted(self.external_signals, key=lambda x: str(x.get("id", "")))],
            "flags": [f.to_dict() for f in sorted(self.flags, key=lambda x: x.id)],
            "warnings": list(self.warnings),
        }

    @property
    def has_cross_user_duplicate(self) -> bool:
        return bool(self.duplicates) and any(p.cross_user for p in self.duplicates.pairs)

    @property
    def has_duplicate(self) -> bool:
        return bool(self.duplicates) and bool(self.duplicates.pairs)


def collect_signals(path_or_data) -> list[dict]:
    """Read a ``--signals`` file into a list of dicts, keyed by ``id`` or ``path`` when present."""
    if path_or_data is None:
        return []
    data = path_or_data
    if isinstance(data, (str, os.PathLike)) and os.path.exists(data):
        try:
            data = json.loads(open(data, encoding="utf-8").read())
        except json.JSONDecodeError as exc:
            raise SimilarityError(f"signals file {data} is not valid JSON: {exc}") from exc
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise SimilarityError(f"signals are not valid JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("signals") or data.get("results") or []
    if not isinstance(data, list):
        raise SimilarityError("signals must be a list, or an object with a 'signals' list")
    return [dict(item) for item in data if isinstance(item, dict)]


def _signal_keys(signal: dict) -> set[str]:
    keys = set()
    for field_name in ("id", "path", "submission", "file"):
        value = signal.get(field_name)
        if isinstance(value, str) and value:
            keys.add(value)
            keys.add(os.path.normpath(value))
    return keys


def build_audit(submissions: list[Submission], *, store: ProfileStore | None = None,
                signals=None, min_evidence: int = 3, on_progress=None, **dup_kwargs) -> AuditReport:
    """Run the duplicate pass, the per-user style comparison, and merge in external signals.

    ``on_progress`` hears from both long phases: the duplicate pass reports its own stages, and the
    style comparison reports ``style`` per submission - it re-reads every file, so leaving it out
    would look like the pass had stalled.
    """
    report = AuditReport()
    subs = sorted(submissions, key=lambda s: s.id)
    report.duplicates = find_duplicates(subs, on_progress=on_progress, **dup_kwargs)
    report.warnings.extend(report.duplicates.warnings)

    by_id = {s.id: s for s in subs}
    by_path = {os.path.normpath(s.path): s for s in subs}
    for position, signal in enumerate(collect_signals(signals)):
        keys = _signal_keys(signal)
        target = next((by_id[k] for k in keys if k in by_id), None) or \
            next((by_path[k] for k in keys if k in by_path), None)
        if target is None:
            report.warnings.append(f"unmatched-signal:{sorted(keys)[0] if keys else position}")
        else:
            signal["id"] = target.id  # normalise the join key so consumers can group by submission
        report.external_signals.append(signal)

    flagged: dict[str, set[str]] = {}
    for pair in report.duplicates.pairs:
        for side, user in ((pair.a, pair.user_a), (pair.b, pair.user_b)):
            reason = "cross-user-duplicate" if pair.cross_user else "same-user-duplicate"
            flagged.setdefault(side, set()).add(reason)
    for signal in report.external_signals:
        target = signal.get("id")
        if target in by_id:
            flagged.setdefault(target, set()).add("external-signal")

    if store is None:
        report.warnings.append("no-profile-store:style deviation skipped")
    style_started = time.perf_counter()
    for position, sub in enumerate(subs, 1):
        # counted as examined, before this submission's branch: the skips are work too, and a
        # progress line that only moved on the slow path would stall in a corpus with no profiles
        if on_progress is not None:
            on_progress(ProgressEvent("style", position, len(subs),
                                      time.perf_counter() - style_started))
        profile = store.get(sub.user) if store is not None else None
        if profile is None:
            if store is not None:
                report.warnings.append(f"no-profile:{sub.id}:{sub.user}")
            continue
        try:
            doc = read_document(sub)
        except SimilarityError as exc:
            report.warnings.append(f"unreadable:{sub.id}")
            continue
        audit = analyze([doc], baseline=profile, min_evidence=min_evidence)
        if not audit.findings:
            continue
        worst = max((f.severity for f in audit.findings), key=lambda s: SEVERITY_RANK.get(s, 0))
        report.style_deviations.append(
            StyleDeviation(sub.id, sub.user, len(audit.findings), worst,
                           tuple(sorted({f.rule for f in audit.findings})))
        )
        flagged.setdefault(sub.id, set()).add("style-deviation")

    report.flags = [Flag(identifier, tuple(sorted(reasons))) for identifier, reasons in sorted(flagged.items())]
    chained = [c for c in report.duplicates.clusters if c.size > 2]
    if chained:
        report.warnings.append(f"transitive-clusters:{len(chained)}")
    return report
