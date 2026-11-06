"""Command line entry point: extract, check, profile, format.

Messages, reports and ``--help`` come out in English or Chinese: ``-L zh`` /
``--msg-lang zh`` (accepted anywhere on the command line) or ``CF_LANG=zh``.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from . import __version__
from .audit import build_audit
from .consistency import analyze
from .document import build_document
from .extract import extract_all
from .format import FormatOptions, Formatter
from .i18n import ENV_VAR, get_locale, set_locale, t
from .profile import FEATURE_SPECS, Profile
from .report import (
    render_consistency,
    render_duplicates,
    render_format,
    render_languages,
    render_profile,
    render_rules,
    render_similarity,
    render_audit,
    render_store,
    rule_summary,
)
from .similarity import (
    Submission,
    SimilarityError,
    compare_documents,
    find_duplicates,
    load_manifest,
)
from .sources import ENCODINGS, InputError, decode_bytes, read_bytes, read_source, write_source
from .store import ProfileStore, StoreError
from .tokens import SPEC_BY_NAME

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2
SEVERITY_RANK = {"none": -1, "low": 0, "medium": 1, "high": 2}
DEFAULT_STORE = os.path.join("~", ".code-feature", "profiles.json")


def expand_paths(paths: list[str]) -> list[str]:
    """Expand globs: cmd.exe and PowerShell do not expand ``src\\*.cpp`` for us."""
    out: list[str] = []
    for pattern in paths:
        if pattern == "-":
            out.append(pattern)
            continue
        if any(ch in pattern for ch in "*?["):
            matches = sorted(glob.glob(pattern, recursive=True))
            if not matches:
                raise InputError(t("e.no_glob_match", pattern=repr(pattern)))
            out.extend(matches)
        else:
            out.append(pattern)
    return out


def load_inputs(paths: list[str], lang: str | None = None) -> tuple[list, list[tuple[str, str]]]:
    """Return (documents, [(path, encoding)]).  No paths, or ``-``, reads stdin."""
    spec = None
    if lang:
        if lang not in SPEC_BY_NAME:
            raise InputError(t("e.unknown_lang", name=repr(lang), options=", ".join(sorted(SPEC_BY_NAME))))
        spec = SPEC_BY_NAME[lang]
    paths = expand_paths(list(paths or []))
    if not paths or paths == ["-"]:
        raw = sys.stdin.buffer.read()
        text, enc = decode_bytes(raw)
        return [build_document(text, "<stdin>", spec)], [("<stdin>", enc)]
    docs, meta = [], []
    for path in paths:
        text, enc = read_source(path)
        docs.append(build_document(text, path, spec))
        meta.append((path, enc))
    return docs, meta


def profile_from_args(args, store: ProfileStore) -> Profile:
    user = getattr(args, "user", None)
    path = getattr(args, "profile", None)
    if user and path:
        raise InputError(t("e.both_sources"))
    if user:
        return store.require(user)
    if path:
        try:
            text, _enc = read_source(path)
            data = json.loads(text)
        except OSError as exc:
            raise InputError(t("e.bad_profile_path", path=path, error=exc.strerror or exc)) from exc
        except json.JSONDecodeError as exc:
            raise InputError(t("e.bad_profile_json", path=path, error=exc)) from exc
        if "users" in data:
            names = list(data["users"])
            if not names:
                raise InputError(t("e.profile_empty_file", path=path))
            return Profile.from_dict(data["users"][names[0]])
        return Profile.from_dict(data)
    raise InputError(t("e.need_profile"))


def options_from_args(args) -> FormatOptions:
    rules = None
    if getattr(args, "rules", None):
        rules = {r.strip() for r in args.rules.split(",") if r.strip()}
        unknown = sorted(rules - set(FEATURE_SPECS))
        if unknown:
            raise InputError(t("e.unknown_rules", rules=", ".join(unknown)))
    return FormatOptions(
        rules=rules,
        min_confidence=args.min_confidence,
        use_defaults=not args.observed_only,
        wrap=not args.no_wrap,
        eol={"lf": "\n", "crlf": "\r\n"}.get(getattr(args, "eol", "keep"), None),
    )


# -- commands ---------------------------------------------------------------


def cmd_extract(args) -> int:
    docs, _meta = load_inputs(args.files, args.lang)
    store = ProfileStore(args.store)
    if args.user:
        profile = store.add_from_samples(args.user, docs, replace=args.replace)
        store.flush()
    else:
        profile = extract_all(docs)
    if args.out:
        write_source(args.out, json.dumps(profile.to_dict(), indent=2, ensure_ascii=False) + "\n", "utf-8")
    if args.json:
        print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_profile(profile, min_confidence=args.min_confidence, show_rows=args.show_rows))
        if args.user:
            print()
            print(t("c.saved", user=profile.user, path=store.path))
    return EXIT_OK


def cmd_check(args) -> int:
    docs, _meta = load_inputs(args.files, args.lang)
    store = ProfileStore(args.store)
    baseline = profile_from_args(args, store) if (args.user or args.profile) else None
    report = analyze(docs, baseline=baseline, min_evidence=args.min_evidence)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_consistency(report, max_findings=args.max_findings, show_all=args.all))
        if args.show_rules:
            rows = rule_summary(report)
            if rows:
                print(t("r.rule_agreement"))
                print("\n".join(f"  {line}" for line in rows))
    threshold = SEVERITY_RANK.get(args.fail_on, 2)
    worst = max((SEVERITY_RANK.get(f.severity, 0) for f in report.findings), default=-1)
    return EXIT_FINDINGS if threshold >= 0 and worst >= threshold else EXIT_OK


def cmd_profile(args) -> int:
    store = ProfileStore(args.store)
    action = args.action
    if action == "list":
        if args.json:
            print(json.dumps([s.__dict__ for s in store.summaries()], indent=2, ensure_ascii=False))
        else:
            print(render_store(store.summaries(), store.path))
        return EXIT_OK
    if action in ("add", "update"):
        if not args.files:
            raise InputError(t("e.need_samples", action=f"profile {action}"))
        docs, _meta = load_inputs(args.files, args.lang)
        replace = action == "add" and args.replace
        name = args.name.strip() if args.name and args.name.strip() else "default"
        existed = store.get(name) is not None
        profile = store.add_from_samples(args.name, docs, replace=replace)
        store.flush()
        if args.json:
            print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
        else:
            if not existed:
                key = "c.created"
            elif replace:
                key = "c.replaced"
            else:
                key = "c.updated"
            print(t(key, user=profile.user, count=len(docs), language=profile.language))
            print(t("r.store_path", path=store.path))
            print(render_profile(profile, min_confidence=args.min_confidence))
        return EXIT_OK
    if action == "show":
        profile = store.require(args.name)
        if args.json:
            print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(render_profile(profile, min_confidence=args.min_confidence, show_rows=args.show_rows))
        return EXIT_OK
    if action == "delete":
        if not store.remove(args.name):
            raise InputError(t("e.no_such_profile", name=repr(args.name)))
        store.flush()
        print(t("c.deleted", user=args.name))
        return EXIT_OK
    if action == "rename":
        profile = store.rename(args.name, args.new_name)
        store.flush()
        print(t("c.renamed", old=args.name, new=profile.user))
        return EXIT_OK
    if action == "export":
        text = store.export(args.name)
        if args.out:
            write_source(args.out, text, "utf-8")
            print(t("c.exported", user=args.name, path=args.out))
        else:
            print(text, end="")
        return EXIT_OK
    if action == "import":
        text, _enc = read_source(args.file)
        profile = store.import_json(text, user=args.name, replace=args.replace)
        store.flush()
        print(t("c.imported", user=profile.user, count=len(profile.samples), path=store.path))
        return EXIT_OK
    raise InputError(t("e.unknown_action", action=repr(action)))


def cmd_format(args) -> int:
    docs, meta = load_inputs(args.files, args.lang)
    store = ProfileStore(args.store)
    profile = profile_from_args(args, store)
    options = options_from_args(args)
    results = []
    refused = []
    for (path, enc), doc in zip(meta, docs):
        res = Formatter(doc, profile, options).run()
        results.append((path, res, enc, doc.src))
        if res.error:
            refused.append(path)
    from_stdin = len(meta) == 1 and meta[0][0] == "<stdin>"
    # ``--json`` owns stdout: the formatted text travels inside the payload instead of being
    # printed in front of it, otherwise the stream would not be a single JSON document.
    if from_stdin and not args.check and not args.json:
        sys.stdout.write(results[0][1].text)
    elif args.write and not from_stdin:
        for path, res, enc, _before in results:
            if res.changed and not res.error:
                write_source(path, res.text, enc)
    if args.json:
        payload = {
            "profile": profile.user,
            "locale": get_locale(),
            "mode": "write" if args.write else "check" if args.check else "preview",
            "files": [
                {
                    "file": path,
                    "changed": res.changed,
                    "applied": res.applied,
                    "skipped": res.skipped,
                    "error": res.error,
                    **({"text": res.text} if from_stdin else {}),
                }
                for path, res, _enc, _before in results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif not from_stdin:
        print(render_format([(p, r, before) for p, r, _enc, before in results], diffs=args.diff))
    if refused:
        print(t("e.refused_files", count=len(refused), names=", ".join(refused)), file=sys.stderr)
        return EXIT_ERROR
    changed_any = any(res.changed for _p, res, _e, _b in results)
    if args.check and changed_any:
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_dup(args) -> int:
    subs = _submissions_from_args(args)
    report = find_duplicates(
        subs,
        min_jaccard=args.min_score,
        min_containment=args.min_containment,
        min_shared=args.min_shared,
        min_tokens=args.min_tokens,
        same_problem=not args.all_problems,
        same_language=not args.cross_language,
        include_same_user=not args.cross_user,
        include_cross_user=not args.same_user,
        max_candidates=args.max_candidates,
        evidence=args.evidence,
        k=args.k,
        window=args.window,
        winnow=not args.no_winnow,
        keep_common=args.keep_common,
        max_df=args.max_df,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_duplicates(report, top=args.top, show_all=args.all))
    policy = args.fail_on or ("cross-user" if args.manifest else "any")
    if policy == "none" or not report.pairs:
        return EXIT_OK
    if policy == "any":
        return EXIT_FINDINGS
    return EXIT_FINDINGS if any(p.cross_user for p in report.pairs) else EXIT_OK


def cmd_similar(args) -> int:
    paths = expand_paths(list(args.files or []))
    if len(paths) != 2:
        raise InputError(t("e.similar_two", count=len(paths)))
    docs = []
    for path in paths:
        text, _enc = read_source(path)
        docs.append(build_document(text, path, _spec_for(args.lang)))
    sim = compare_documents(
        docs[0], docs[1], k=args.k, window=args.window, min_shared=args.min_shared,
        min_tokens=args.min_tokens, winnow=not args.no_winnow, evidence=args.evidence,
        min_jaccard=args.min_score, min_containment=args.min_containment,
    )
    if args.json:
        print(json.dumps({"pair": sim.to_dict()}, indent=2, ensure_ascii=False))
    else:
        print(render_similarity(sim, evidence_limit=args.evidence))
    return EXIT_OK


def _spec_for(lang: str | None):
    if not lang:
        return None
    if lang not in SPEC_BY_NAME:
        raise InputError(t("e.unknown_lang", name=repr(lang), options=", ".join(sorted(SPEC_BY_NAME))))
    return SPEC_BY_NAME[lang]


def _submissions_from_args(args) -> list[Submission]:
    """A manifest carries user/problem metadata; bare file paths all belong to ``unknown``."""
    if getattr(args, "manifest", None):
        return load_manifest(args.manifest)
    paths = expand_paths(list(args.files or []))
    if not paths:
        raise InputError(t("e.dup_no_inputs"))
    return [Submission(path=p, user="unknown") for p in sorted(paths)]


def cmd_audit(args) -> int:
    subs = _submissions_from_args(args)
    store = ProfileStore(args.store)
    report = build_audit(
        subs,
        store=store,
        signals=args.signals,
        min_evidence=args.min_evidence,
        min_jaccard=args.min_score,
        min_containment=args.min_containment,
        min_shared=args.min_shared,
        min_tokens=args.min_tokens,
        same_problem=not args.all_problems,
        same_language=not args.cross_language,
        evidence=args.evidence,
        k=args.k,
        window=args.window,
        winnow=not args.no_winnow,
        keep_common=args.keep_common,
        max_df=args.max_df,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_audit(report))
    if args.fail_on == "none":
        return EXIT_OK
    if args.fail_on == "any" and (report.duplicates.pairs or report.style_deviations or report.external_signals):
        return EXIT_FINDINGS
    if report.has_cross_user_duplicate:
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_rules(args) -> int:
    print(render_rules())
    return EXIT_OK


def cmd_languages(args) -> int:
    print(render_languages(sorted(SPEC_BY_NAME.items())))
    return EXIT_OK


# -- parser -----------------------------------------------------------------

EPILOG = {
    "en": (
        "examples:\n"
        "  cf profile add bin --lang cpp src/*.cpp          learn a profile from samples\n"
        "  cf extract src/*.py                              show what the samples imply\n"
        "  cf check src/*.cpp --user bin --fail-on medium   audit against a stored profile\n"
        "  cf format --user bin --check src/*.cpp           CI gate: would anything move?\n"
        "  cf format --user bin --write src/*.cpp           reformat in place\n"
        "  cf format --profile bin.json < main.c            read stdin, write stdout\n"
        "  cf -L zh check src/*.py                          report in Chinese\n"
        "  cf dup --manifest subs.json                      find cross-user duplicates\n"
        "  cf similar alice.cpp bob.cpp                     score one pair\n"
    ),
    "zh": (
        "示例：\n"
        "  cf profile add bin --lang cpp src/*.cpp          从样本学习一份个人风格档案\n"
        "  cf extract src/*.py                              查看样本体现出的风格\n"
        "  cf check src/*.cpp --user bin --fail-on medium   对照已存档案做一致性检查\n"
        "  cf format --user bin --check src/*.cpp           CI 门禁：会不会有改动\n"
        "  cf format --user bin --write src/*.cpp           就地格式化\n"
        "  cf format --profile bin.json < main.c            标准输入进、标准输出出\n"
        "  cf -L zh check src/*.py                          用中文输出提示\n"
        "  cf dup --manifest subs.json                      在多用户提交里查找重复\n"
        "  cf similar alice.cpp bob.cpp                     只比较一对文件\n"
    ),
}


def add_common(parser: argparse.ArgumentParser, files_help: str) -> None:
    parser.add_argument("files", nargs="*", help=files_help)
    parser.add_argument("--lang", help=t("h.lang"))
    parser.add_argument("--store", help=t("h.store", default=DEFAULT_STORE))
    parser.add_argument("--json", action="store_true", help=t("h.json"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cf",
        description=t("h.summary"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG[get_locale()],
    )
    parser.add_argument("--version", action="version", version=f"cf {__version__}")
    parser.add_argument("-L", "--msg-lang", choices=("en", "zh"), default=None, help=t("h.msg_lang"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help=t("h.lh.extract"))
    add_common(p, t("h.files"))
    p.add_argument("--user", help=t("h.user_extract"))
    p.add_argument("--replace", action="store_true", help=t("h.replace"))
    p.add_argument("--out", help=t("h.out"))
    p.add_argument("--min-confidence", type=float, default=0.0, help=t("h.min_conf"))
    p.add_argument("--show-rows", action="store_true", help=t("h.show_rows"))
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("check", help=t("h.lh.check"))
    add_common(p, t("h.files"))
    p.add_argument("--user", help=t("h.check_user"))
    p.add_argument("--profile", help=t("h.check_profile"))
    p.add_argument("--min-evidence", type=int, default=3, help=t("h.min_evidence"))
    p.add_argument("--max-findings", type=int, default=40, help=t("h.max_findings"))
    p.add_argument("--all", action="store_true", help=t("h.all"))
    p.add_argument("--show-rules", action="store_true", help=t("h.show_rules"))
    p.add_argument("--fail-on", choices=("none", "low", "medium", "high"), default="high", help=t("h.fail_on"))
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("profile", help=t("h.lh.profile"))
    subp = p.add_subparsers(dest="action", required=True)

    def profile_flags(sp):
        sp.add_argument("--store", help=t("h.store", default=DEFAULT_STORE))
        sp.add_argument("--json", action="store_true", help=t("h.json"))
        sp.add_argument("--min-confidence", type=float, default=0.0, help=t("h.min_conf"))
        sp.add_argument("--show-rows", action="store_true", help=t("h.show_rows"))
        return sp

    a = profile_flags(subp.add_parser("add", help=t("h.lh.add")))
    a.add_argument("name", help=t("h.name"))
    a.add_argument("files", nargs="*", help=t("h.files.profile"))
    a.add_argument("--lang", help=t("h.lang"))
    a.add_argument("--replace", action="store_true", help=t("h.replace"))
    s = profile_flags(subp.add_parser("show", help=t("h.lh.show")))
    s.add_argument("name", help=t("h.name"))
    u = profile_flags(subp.add_parser("update", help=t("h.lh.update")))
    u.add_argument("name", help=t("h.name"))
    u.add_argument("files", nargs="*", help=t("h.files.profile"))
    u.add_argument("--lang", help=t("h.lang"))
    profile_flags(subp.add_parser("list", help=t("h.lh.list")))
    d = profile_flags(subp.add_parser("delete", help=t("h.lh.delete")))
    d.add_argument("name", help=t("h.name"))
    r = profile_flags(subp.add_parser("rename", help=t("h.lh.rename")))
    r.add_argument("name", help=t("h.name"))
    r.add_argument("new_name", help=t("h.new_name"))
    e = profile_flags(subp.add_parser("export", help=t("h.lh.export")))
    e.add_argument("name", help=t("h.name"))
    e.add_argument("--out", help=t("h.out"))
    i = profile_flags(subp.add_parser("import", help=t("h.lh.import")))
    i.add_argument("file", help=t("h.profile_file"))
    i.add_argument("name", nargs="?", help=t("h.name"))
    i.add_argument("--replace", action="store_true", help=t("h.replace"))
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("format", help=t("h.lh.format"))
    add_common(p, t("h.files"))
    target = p.add_mutually_exclusive_group()
    target.add_argument("--user", help=t("h.format_user"))
    target.add_argument("--profile", help=t("h.format_profile"))
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--write", "-i", action="store_true", help=t("h.write"))
    mode.add_argument("--check", action="store_true", help=t("h.check"))
    p.add_argument("--diff", action="store_true", help=t("h.diff"))
    p.add_argument("--rules", help=t("h.rules"))
    p.add_argument("--min-confidence", type=float, default=0.5, help=t("h.min_conf.format"))
    p.add_argument("--observed-only", action="store_true", help=t("h.observed_only"))
    p.add_argument("--no-wrap", action="store_true", help=t("h.no_wrap"))
    p.add_argument("--eol", choices=("keep", "lf", "crlf"), default="keep", help=t("h.eol"))
    p.set_defaults(func=cmd_format)

    p = sub.add_parser("dup", help=t("h.lh.dup"),
                       description=t("h.dup.summary"),
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*", help=t("h.dup.files"))
    p.add_argument("--manifest", help=t("h.dup.manifest"))
    p.add_argument("--store", help=t("h.store", default=DEFAULT_STORE))
    p.add_argument("--json", action="store_true", help=t("h.json"))
    p.add_argument("--min-score", type=float, default=0.5, help=t("h.dup.min_score"))
    p.add_argument("--min-containment", type=float, default=0.8, help=t("h.dup.min_containment"))
    p.add_argument("--min-shared", type=int, default=3, help=t("h.dup.min_shared"))
    p.add_argument("--min-tokens", type=int, default=80, help=t("h.dup.min_tokens"))
    p.add_argument("--k", type=int, default=7, help=t("h.dup.k"))
    p.add_argument("--window", type=int, default=4, help=t("h.dup.window"))
    p.add_argument("--no-winnow", action="store_true", help=t("h.dup.no_winnow"))
    p.add_argument("--keep-common", action="store_true", help=t("h.dup.keep_common"))
    p.add_argument("--max-df", type=float, default=0.8, help=t("h.dup.max_df"))
    group = p.add_mutually_exclusive_group()
    group.add_argument("--cross-user", action="store_true", help=t("h.dup.cross_user"))
    group.add_argument("--same-user", action="store_true", help=t("h.dup.same_user"))
    p.add_argument("--all-problems", action="store_true", help=t("h.dup.all_problems"))
    p.add_argument("--cross-language", action="store_true", help=t("h.dup.cross_language"))
    p.add_argument("--max-candidates", type=int, help=t("h.dup.max_candidates"))
    p.add_argument("--evidence", type=int, default=3, help=t("h.dup.evidence"))
    p.add_argument("--top", type=int, default=50, help=t("h.dup.top"))
    p.add_argument("--all", action="store_true", help=t("h.dup.all"))
    p.add_argument("--fail-on", choices=("none", "any", "cross-user"),
                   help=t("h.dup.fail_on"), default=None)
    p.set_defaults(func=cmd_dup)

    p = sub.add_parser("similar", help=t("h.lh.similar"),
                       description=t("h.similar.summary"),
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*", help=t("h.similar.files"))
    p.add_argument("--lang", help=t("h.lang"))
    p.add_argument("--json", action="store_true", help=t("h.json"))
    p.add_argument("--k", type=int, default=7, help=t("h.dup.k"))
    p.add_argument("--window", type=int, default=4, help=t("h.dup.window"))
    p.add_argument("--no-winnow", action="store_true", help=t("h.dup.no_winnow"))
    p.add_argument("--min-score", type=float, default=0.5, help=t("h.dup.min_score"))
    p.add_argument("--min-containment", type=float, default=0.8, help=t("h.dup.min_containment"))
    p.add_argument("--min-shared", type=int, default=3, help=t("h.dup.min_shared"))
    p.add_argument("--min-tokens", type=int, default=80, help=t("h.dup.min_tokens"))
    p.add_argument("--evidence", type=int, default=3, help=t("h.dup.evidence"))
    p.set_defaults(func=cmd_similar)

    p = sub.add_parser("audit", help=t("h.lh.audit"),
                       description=t("h.audit.summary"),
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*", help=t("h.dup.files"))
    p.add_argument("--manifest", help=t("h.dup.manifest"))
    p.add_argument("--store", help=t("h.audit.store"))
    p.add_argument("--signals", help=t("h.audit.signals"))
    p.add_argument("--json", action="store_true", help=t("h.json"))
    p.add_argument("--min-score", type=float, default=0.5, help=t("h.dup.min_score"))
    p.add_argument("--min-containment", type=float, default=0.8, help=t("h.dup.min_containment"))
    p.add_argument("--min-shared", type=int, default=3, help=t("h.dup.min_shared"))
    p.add_argument("--min-tokens", type=int, default=80, help=t("h.dup.min_tokens"))
    p.add_argument("--min-evidence", type=int, default=3, help=t("h.min_evidence"))
    p.add_argument("--k", type=int, default=7, help=t("h.dup.k"))
    p.add_argument("--window", type=int, default=4, help=t("h.dup.window"))
    p.add_argument("--no-winnow", action="store_true", help=t("h.dup.no_winnow"))
    p.add_argument("--keep-common", action="store_true", help=t("h.dup.keep_common"))
    p.add_argument("--max-df", type=float, default=0.8, help=t("h.dup.max_df"))
    p.add_argument("--all-problems", action="store_true", help=t("h.dup.all_problems"))
    p.add_argument("--cross-language", action="store_true", help=t("h.dup.cross_language"))
    p.add_argument("--evidence", type=int, default=3, help=t("h.dup.evidence"))
    p.add_argument("--fail-on", choices=("none", "duplicate", "any"), default="duplicate",
                   help=t("h.audit.fail_on"))
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("rules", help=t("h.lh.rules"))
    p.set_defaults(func=cmd_rules)
    p = sub.add_parser("languages", help=t("h.lh.languages"))
    p.set_defaults(func=cmd_languages)
    return parser


def split_msg_lang(argv: list[str]) -> tuple[list[str], str | None]:
    """Pull ``-L``/``--msg-lang`` out of argv so it can sit anywhere in the command line."""
    rest: list[str] = []
    value: str | None = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("-L", "--msg-lang"):
            value = argv[i + 1] if i + 1 < len(argv) else None
            i += 2
            continue
        if token.startswith("--msg-lang="):
            value = token.split("=", 1)[1]
            i += 1
            continue
        rest.append(token)
        i += 1
    return rest, value


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, flag = split_msg_lang(argv)
    set_locale(flag or os.environ.get(ENV_VAR))
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "max_findings", None) == 0:
        args.all = True
    try:
        return args.func(args)
    except (InputError, StoreError) as exc:
        print(f"cf: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except SimilarityError as exc:
        print(f"cf: {t('e.similarity', error=exc)}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print(t("e.interrupted"), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
