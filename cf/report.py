"""Human-readable rendering of profiles, inconsistency reports and format runs.

Columns are padded by *display* width: Chinese glyphs take two terminal cells, so plain
``{:<32}`` padding would drift out of alignment in Chinese output.
"""
from __future__ import annotations

import difflib
import sys
import time
from unicodedata import east_asian_width

from .format import FORMAT_RULES, NOT_REWRITTEN
from .i18n import get_locale, kind_label, rule_label, t, translate_value
from .profile import FEATURE_SPECS, Profile

BAR_WIDTH = 10
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def display_width(text) -> int:
    """Columns a string occupies in a terminal: CJK glyphs take two."""
    return sum(2 if east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def pad(text, width: int, align: str = "left") -> str:
    text = str(text)
    fill = max(0, width - display_width(text))
    return (" " * fill + text) if align == "right" else (text + " " * fill)


def line(cells: list[tuple[object, int, str]]) -> str:
    return "  ".join(pad(value, width, align) for value, width, align in cells).rstrip()


def bar(confidence: float) -> str:
    filled = int(round(max(0.0, min(1.0, confidence)) * BAR_WIDTH))
    return "[" + "#" * filled + "-" * (BAR_WIDTH - filled) + f"] {confidence:.2f}"


def when(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (ValueError, OSError):
        return "?"


def render_profile(profile: Profile, min_confidence: float = 0.0, show_rows: bool = False) -> str:
    zh = get_locale() == "zh"
    key_w, val_w = (44, 16) if zh else (34, 22)
    lines: list[str] = []
    lines.append(t("r.profile_head", user=profile.user, language=profile.language, family=profile.family))
    lines.append(
        t("r.profile_meta", samples=len(profile.samples), updated=when(profile.updated), created=when(profile.created))
    )
    stats = profile.stats
    if stats:
        pairs = "  ".join(
            f"{k}={stats[k]}"
            for k in ("rows", "code_rows", "max_line_width", "p95_line_width", "over_limit_rows", "tokens", "comments")
            if k in stats
        )
        lines.append(t("r.measurements", pairs=pairs))
    lines.append("")
    header = line([(t("r.col.rule"), key_w, "left"), (t("r.col.value"), val_w, "left"),
                   (t("r.col.evidence"), 10, "right"), (t("r.col.confidence"), 0, "left")])
    lines.append(header)
    rule_line = "-" * display_width(header)
    lines.append(rule_line)
    observed = 0
    defaults: list[str] = []
    for item in profile.table():
        if not item["observed"]:
            defaults.append(f"{item['key']}={translate_value(item['value'])}")
            continue
        if item["confidence"] < min_confidence:
            continue
        observed += 1
        key = f"{item['key']} {rule_label(item['key'])}" if zh else item["key"]
        lines.append(
            line([(key, key_w, "left"), (translate_value(item["value"]), val_w, "left"),
                  (f"{item['support']}/{item['total']}", 10, "right"), (bar(item["confidence"]), 0, "left")])
        )
        if show_rows:
            feat = profile.feature(item["key"])
            for other, rows in (feat.outlier_rows(6) if feat else []):
                lines.append(
                    " " * (key_w + 2) + t("r.deviating", value=translate_value(other), rows=", ".join(str(r) for r in rows))
                )
    lines.append(rule_line)
    lines.append(t("r.observed_count", count=observed))
    if defaults:
        lines.append(t("r.unset", items=", ".join(defaults[:12])))
        if len(defaults) > 12:
            lines.append(" " * 24 + t("r.more_items", count=len(defaults) - 12))
    return "\n".join(lines)


def render_store(summaries, store_path: str) -> str:
    if not summaries:
        return t("r.store_empty", path=store_path)
    lines = [t("r.store_path", path=store_path), ""]
    header = line(
        [(t("r.col.user"), 20, "left"), (t("r.col.language"), 12, "left"), (t("r.col.samples"), 8, "right"),
         (t("r.col.rows"), 7, "right"), (t("r.col.confident"), 10, "right"), (t("r.col.updated"), 0, "left")]
    )
    lines.append(header)
    lines.append("-" * display_width(header))
    for s in summaries:
        lines.append(
            line([(s.user[:19], 20, "left"), (s.language, 12, "left"), (s.samples, 8, "right"), (s.rows, 7, "right"),
                  (s.confident_features, 10, "right"), (when(s.updated), 0, "left")])
        )
    return "\n".join(lines)


def render_consistency(report, max_findings: int = 40, show_all: bool = False) -> str:
    lines: list[str] = []
    lines.append(
        t("r.consistency_head", score=f"{report.score * 100:.1f}", samples=report.samples, baseline=report.baseline.user)
    )
    lines.append("")
    header = line(
        [(t("r.col.file"), 44, "left"), (t("r.col.score"), 8, "right"), (t("r.col.rows"), 6, "right"),
         (t("r.col.findings"), 9, "right")]
    )
    lines.append(header)
    lines.append("-" * display_width(header))
    for f in report.files:
        shown = f.file if display_width(f.file) <= 43 else "..." + f.file[-40:]
        lines.append(
            line([(shown, 44, "left"), (f"{f.score * 100:.1f}%", 8, "right"), (f.rows, 6, "right"), (f.findings, 9, "right")])
        )
    lines.append("")
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in report.findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    lines.append(t("r.findings_count", total=len(report.findings), **counts))
    if not report.findings:
        lines.append(t("r.no_findings"))
        return "\n".join(lines)
    lines.append("")
    limit = len(report.findings) if show_all else max(0, max_findings)
    printed = 0
    by_file: dict[str, list] = {}
    for finding in sorted(report.findings, key=lambda f: (f.file, SEVERITY_ORDER.get(f.severity, 3), f.rule)):
        by_file.setdefault(finding.file, []).append(finding)
    for path, items in by_file.items():
        lines.append(path)
        for finding in items:
            if printed >= limit:
                break
            printed += 1
            rows = ", ".join(str(r) for r in finding.rows)
            more = " " + t("r.extra_rows", count=finding.extra_rows) if finding.extra_rows else ""
            tag = pad(translate_value(finding.severity, kind="severity"), 4)
            scope = pad(t("r.scope_intra") if finding.kind == "intra-file" else t("r.scope_profile"), 16)
            lines.append(f"  [{tag}] {scope} {pad(finding.rule, 28)} {t('r.line')} {rows}{more}")
            lines.append(f"          {finding.message}")
        lines.append("")
    if printed < len(report.findings):
        lines.append(t("r.suppressed", count=len(report.findings) - printed))
    return "\n".join(lines)


def rule_summary(report) -> list[str]:
    """Per-rule agreement, for the --show-rules view of a check run."""
    out = []
    for item in report.rules:
        if item["findings"]:
            out.append(
                line([(item["rule"], 32, "left"), (f"value={translate_value(item['value'])}", 22, "left"),
                      (f"agreement={item['agreement']:.2f}", 18, "left"), (f"findings={item['findings']}", 0, "left")])
            )
    return out


def render_format(results, diffs: bool = False) -> str:
    """results: iterable of (path, FormatResult, before_text)."""
    lines: list[str] = []
    changed = 0
    for path, res, before in results:
        if res.error:
            lines.append(t("r.fmt_refused", path=path, error=res.error))
            continue
        if res.changed:
            changed += 1
            lines.append(t("r.fmt_changed", path=path, rules=", ".join(res.applied) or "-"))
        else:
            lines.append(t("r.fmt_same", path=path))
        if res.skipped:
            lines.append("    " + t("r.fmt_skipped", rules=", ".join(res.skipped)))
        if diffs and res.changed:
            lines.append(indent_block(diff_for(path, before, res.text)))
    lines.append("")
    lines.append(t("r.fmt_total", count=changed))
    return "\n".join(lines)


def diff_for(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path} [{t('d.current')}]",
            tofile=f"{path} [{t('d.formatted')}]",
            n=2,
        )
    )


def indent_block(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.rstrip("\n").split("\n"))


def render_rules() -> str:
    zh = get_locale() == "zh"
    header = line(
        [(t("r.col.rule"), 34, "left"), (t("r.col.kind"), 10, "left"), (t("r.col.role"), 12, "left"),
         (t("r.col.desc"), 0, "left")]
    )
    lines = [header, "-" * display_width(header)]
    for key, spec in sorted(FEATURE_SPECS.items()):
        role = t("r.rules_applies") if key in FORMAT_RULES else t("r.rules_reports")
        desc = rule_label(key) if zh else spec[1]
        lines.append(line([(key, 34, "left"), (kind_label(spec[0]), 10, "left"), (role, 12, "left"), (desc, 0, "left")]))
    lines.append("")
    lines.append(t("r.rules_why"))
    for pattern in NOT_REWRITTEN:
        lines.append(f"  {pad(pattern, 36)} {t('w.' + pattern)}")
    return "\n".join(lines)


def render_languages(specs) -> str:
    header = line(
        [(t("r.col.name"), 14, "left"), (t("r.col.family"), 10, "left"), (t("r.col.files"), 30, "left"),
         (t("r.col.notes"), 0, "left")]
    )
    lines = [header, "-" * display_width(header)]
    exts = {
        "c": ".c .h",
        "cpp": ".cc .cpp .hpp .hh",
        "go": ".go",
        "javascript": ".js .jsx .mjs",
        "typescript": ".ts .tsx",
        "java": ".java",
        "rust": ".rs",
        "csharp": ".cs",
        "shell": ".sh .bash",
        "python": ".py .pyi",
        "clike": t("r.lang_fallback"),
    }
    notes = {"python": t("r.lang_note.python"), "clike": t("r.lang_note.clike")}
    for name, spec in specs:
        lines.append(
            line([(name, 14, "left"), (spec.family, 10, "left"), (exts.get(name, ""), 30, "left"),
                  (notes.get(name, ""), 0, "left")])
        )
    return "\n".join(lines)


def _range(span: tuple[int, int]) -> str:
    return str(span[0]) if span[0] == span[1] else f"{span[0]}-{span[1]}"


def render_similarity(sim, evidence_limit: int = 3) -> str:
    """One pair, for ``cf similar``."""
    lines = [t("r.sim_head", a=sim.a, b=sim.b)]
    lines.append(
        t("r.sim_scores", jaccard=f"{sim.jaccard:.3f}", containment=f"{sim.containment:.3f}",
          shared=sim.shared_ngrams, tokens_a=sim.tokens_a, tokens_b=sim.tokens_b)
    )
    if sim.user_a != "unknown" or sim.user_b != "unknown":
        lines.append(
            t("r.sim_users", user_a=sim.user_a, user_b=sim.user_b,
              scope=t("r.sim_cross_user") if sim.cross_user else t("r.sim_same_user"))
        )
    if sim.problem:
        lines.append(t("r.sim_problem", problem=sim.problem))
    lines.append(t("r.sim_verdict", state=t("r.sim_flagged") if sim.qualifies else t("r.sim_not_flagged")))
    if sim.evidence:
        lines.append("")
        lines.append(t("r.sim_evidence_head"))
        for span in sim.evidence[:evidence_limit]:
            lines.append(
                t("r.sim_evidence_row", rows_a=_range(span.a_lines), rows_b=_range(span.b_lines),
                  tokens=span.tokens)
            )
    if sim.warnings:
        lines.append(t("r.sim_warnings", items=", ".join(sim.warnings)))
    lines.append("")
    lines.append(t("r.sim_note"))
    return "\n".join(lines)


def render_duplicates(report, top: int = 50, show_all: bool = False, note: bool = True) -> str:
    lines: list[str] = []
    shown = report.pairs if show_all else report.pairs[:max(0, top)]
    lines.append(t("r.dup_head", count=len(report.pairs), submissions=len(report.submissions)))
    lines.append("")
    if not report.pairs:
        lines.append(t("r.dup_none"))
    else:
        header = line([(t("r.dup.col.score"), 18, "left"), (t("r.dup.col.a"), 26, "left"),
                       (t("r.dup.col.b"), 26, "left"), (t("r.dup.col.user"), 15, "left"),
                       (t("r.dup.col.problem"), 10, "left"), (t("r.dup.col.evidence"), 0, "right")])
        lines.append(header)
        lines.append("-" * display_width(header))
        for p in shown:
            users = f"{p.user_a}|{p.user_b}" if p.cross_user else f"{p.user_a}(same)"
            lines.append(
                line([(f"J={p.jaccard:.3f} C={p.containment:.3f}", 18, "left"),
                      (_clip(p.a, 26), 26, "left"), (_clip(p.b, 26), 26, "left"),
                      (_clip(users, 15), 15, "left"), (_clip(p.problem or "-", 10), 10, "left"),
                      (str(len(p.evidence)), 0, "right")])
            )
        if len(shown) < len(report.pairs):
            lines.append(t("r.dup_more", count=len(report.pairs) - len(shown)))
    if report.clusters:
        lines.append("")
        lines.append(t("r.dup_clusters", count=len(report.clusters)))
        for c in report.clusters:
            lines.append(
                t("r.dup_cluster_row", cid=c.id, users=", ".join(c.users), size=c.size,
                  jaccard=f"{c.max_jaccard:.3f}")
            )
    warnings = list(report.warnings)
    if warnings:
        lines.append("")
        lines.append(t("r.dup_warnings"))
        for warning in warnings:
            lines.append(f"  - {warning}")
    if note:
        lines.append("")
        lines.append(t("r.sim_note"))
    return "\n".join(lines)


def _clip(text: str, width: int) -> str:
    text = str(text)
    return text if display_width(text) <= width else "..." + text[-(width - 3):]


def render_audit(report) -> str:
    lines: list[str] = []
    lines.append(t("r.audit_head", duplicates=len(report.duplicates.pairs) if report.duplicates else 0,
                   submissions=len(report.duplicates.submissions) if report.duplicates else 0))
    lines.append("")
    lines.append(render_duplicates(report.duplicates, top=20, note=False))
    lines.append("")
    lines.append(t("r.audit_style_head", count=len(report.style_deviations)))
    if not report.style_deviations:
        lines.append(t("r.audit_none"))
    else:
        header = line([(t("r.audit.col.id"), 24, "left"), (t("r.audit.col.user"), 12, "left"),
                       (t("r.audit.col.findings"), 9, "right"), (t("r.audit.col.severity"), 8, "left"),
                       (t("r.audit.col.rules"), 0, "left")])
        lines.append(header)
        lines.append("-" * display_width(header))
        for item in report.style_deviations:
            lines.append(
                line([(_clip(item.id, 24), 24, "left"), (_clip(item.user, 12), 12, "left"),
                      (item.findings, 9, "right"), (translate_value(item.max_severity or "-", kind="severity"), 8, "left"),
                      (", ".join(item.rules[:4]) + (" ..." if len(item.rules) > 4 else ""), 0, "left")])
            )
    lines.append("")
    lines.append(t("r.audit_signals_head", count=len(report.external_signals)))
    for signal in report.external_signals:
        keys = ", ".join(f"{k}={signal[k]}" for k in sorted(signal) if k != "id")
        lines.append(f"  {signal.get('id', '-')}  {keys}")
    if not report.external_signals:
        lines.append(t("r.audit_none"))
    lines.append("")
    lines.append(t("r.audit_flags_head", count=len(report.flags)))
    for flag in report.flags:
        lines.append(f"  {flag.id}  {' + '.join(flag.reasons)}")
    if not report.flags:
        lines.append(t("r.audit_none"))
    if report.warnings:
        lines.append("")
        lines.append(t("r.dup_warnings"))
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    lines.append("")
    lines.append(t("r.audit_note"))
    return "\n".join(lines)


class ProgressPrinter:
    """Stream a long pass's progress to stderr, one line per update, with an estimate of the rest.

    The estimate is the stage's own rate, from the counts the pass reports as it works: there is no
    single overall percentage to show, because how long a pass spends lexing versus taking evidence
    depends on how many pairs the thresholds let through, so a combined figure would be a guess.
    stdout is never touched, so a ``--json`` report stays parseable while these lines scroll.

    Updates are ordinary newline-terminated lines, not an in-place rewrite: a half-written line
    would survive into an error message if the pass raised, and a log file cannot show one anyway.
    """

    def __init__(self, stream=None, every: float = 0.2):
        self.stream = stream if stream is not None else sys.stderr
        self.every = every
        self._started = time.perf_counter()
        # counted from the start, so the first line already carries a rate worth believing
        self._last = self._started

    def event(self, progress) -> None:
        """Hand this to ``find_duplicates(on_progress=...)``; it prints on its own cadence.

        A stage younger than the cadence has no rate to divide by yet, so its first update waits
        for one: otherwise the estimate reads "~0.0s left" when a pool is still starting up, which
        is the kind of number a human would act on.
        """
        now = time.perf_counter()
        done, total = progress.done, progress.total
        if not total or (done < total and (now - self._last < self.every
                                           or progress.elapsed < self.every)):
            return
        self._last = now
        eta = progress.elapsed / done * (total - done)
        self._write(t("r.progress", stage=self._stage(progress.stage), done=done, total=total,
                      pct=100 * done // total, elapsed=f"{progress.elapsed:.1f}",
                      eta=f"{eta:.1f}"))

    def finish(self, files: int, pairs: int) -> None:
        """The last line, so a reader can tell the pass ended instead of just stopping printing."""
        self._write(t("r.progress_done", files=files, pairs=pairs,
                      seconds=f"{time.perf_counter() - self._started:.1f}"))

    @staticmethod
    def _stage(stage: str) -> str:
        if stage == "lex":
            return t("r.progress.lex")
        if stage == "evidence":
            return t("r.progress.evidence")
        if stage == "style":
            return t("r.progress.style")
        return stage

    def _write(self, text: str) -> None:
        self.stream.write(text + "\n")
        self.stream.flush()
