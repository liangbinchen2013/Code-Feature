"""Localised messages for the kernel: every user-visible string goes through here.

``cf`` answers in English by default; ``-L zh`` / ``--msg-lang zh`` (or ``CF_LANG=zh``)
switches reports, error text and ``--help`` to Chinese.  Rule keys stay ASCII so profiles,
JSON and ``--rules`` never depend on the active language.
"""
from __future__ import annotations

import os

SUPPORTED = ("en", "zh")
FALLBACK = "en"
ENV_VAR = "CF_LANG"

# (key, english, chinese)
_MESSAGES: list[tuple[str, str, str]] = [
    # -- profile report -----------------------------------------------------
    ("r.profile_head", "profile: {user}    language: {language} ({family})",
     "档案：{user}    语言：{language}（{family}）"),
    ("r.profile_meta", "samples: {samples}    updated: {updated}    created: {created}",
     "样本数：{samples}    更新时间：{updated}    创建时间：{created}"),
    ("r.measurements", "measurements: {pairs}", "测量值：{pairs}"),
    ("r.observed_count", "{count} rules observed from the samples", "从样本中观测到 {count} 条规则"),
    ("r.unset", "unset (family default used when formatting): {items}",
     "未观测（格式化时改用语言族默认值）：{items}"),
    ("r.more_items", "... and {count} more", "……另有 {count} 条"),
    ("r.deviating", "deviating: {value} at rows {rows}", "偏离取值 {value}，出现在行 {rows}"),
    # -- store report -------------------------------------------------------
    ("r.store_empty", "no profiles stored in {path}", "{path} 中还没有任何档案"),
    ("r.store_path", "profile store: {path}", "档案库：{path}"),
    ("r.col.user", "user", "用户"),
    ("r.col.language", "language", "语言"),
    ("r.col.samples", "samples", "样本"),
    ("r.col.rows", "rows", "行数"),
    ("r.col.confident", "confident", "有证据"),
    ("r.col.rule", "rule", "规则"),
    ("r.col.value", "value", "取值"),
    ("r.col.evidence", "evidence", "证据"),
    ("r.col.confidence", "confidence", "置信度"),
    ("r.col.kind", "kind", "类型"),
    ("r.col.role", "formatter", "格式化"),
    ("r.col.desc", "description", "说明"),
    ("r.col.name", "language", "语言"),
    ("r.col.family", "family", "语族"),
    ("r.col.files", "file names", "文件后缀"),
    ("r.col.notes", "notes", "说明"),
    ("r.col.updated", "updated", "更新于"),
    ("r.col.file", "file", "文件"),
    ("r.col.score", "score", "得分"),
    ("r.col.findings", "findings", "问题数"),
    # -- consistency report -------------------------------------------------
    ("r.consistency_head", "consistency: {score}% over {samples} sample(s), baseline {baseline}",
     "一致性：{score}%（{samples} 个样本，基准：{baseline}）"),
    ("r.findings_count", "findings: {total} total  {high} high  {medium} medium  {low} low",
     "问题：共 {total} 条  高 {high}  中 {medium}  低 {low}"),
    ("r.no_findings", "no style conflicts found", "未发现风格冲突"),
    ("r.scope_intra", "mixed in file", "样本内混用"),
    ("r.scope_profile", "differs from profile", "与档案不一致"),
    ("r.line", "line", "行"),
    ("r.extra_rows", "(+{count} rows)", "（另有 {count} 行）"),
    ("r.suppressed", "... {count} more findings suppressed (use --all or --max-findings)",
     "……另有 {count} 条未显示（用 --all 或 --max-findings）"),
    ("r.rule_agreement", "per-rule agreement:", "各规则一致率："),
    # -- format report ------------------------------------------------------
    ("r.fmt_refused", "{path}: REFUSED - {error}", "{path}：拒绝执行 - {error}"),
    ("r.fmt_changed", "{path}: reformatted ({rules})", "{path}：按档案改写（{rules}）"),
    ("r.fmt_same", "{path}: already matches the profile", "{path}：已符合档案，无需改动"),
    ("r.fmt_skipped", "not applied (low confidence): {rules}", "未应用（证据不足）：{rules}"),
    ("r.fmt_total", "{count} file(s) would change", "{count} 个文件会被改写"),
    # -- rules / languages report ------------------------------------------
    ("r.rules_applies", "applies", "会改写"),
    ("r.rules_reports", "reports only", "仅报告"),
    ("r.rules_why", "why some rules are never rewritten:", "以下规则为什么不动手："),
    ("r.lang_note.python", "tokenize + ast", "tokenize + ast 解析"),
    ("r.lang_note.clike", "used when nothing else matches", "其他语言都不匹配时的兜底"),
    ("r.lang_fallback", "(fallback)", "（兜底）"),
    # -- similarity / duplicate report -------------------------------------
    ("r.sim_head", "pair: {a}  <->  {b}", "对照：{a}  <->  {b}"),
    ("r.sim_scores", "jaccard {jaccard}  containment {containment}  shared {shared} k-gram(s)  "
                     "tokens {tokens_a}/{tokens_b}",
     "Jaccard {jaccard}  包含度 {containment}  共享 {shared} 个 k-gram  token 数 {tokens_a}/{tokens_b}"),
    ("r.sim_users", "users: {user_a} vs {user_b}  ({scope})", "用户：{user_a} 对 {user_b}（{scope}）"),
    ("r.sim_cross_user", "cross-user", "跨用户"),
    ("r.sim_same_user", "same user", "同一用户"),
    ("r.sim_problem", "problem: {problem}", "题目：{problem}"),
    ("r.sim_verdict", "reported: {state}", "是否列入：{state}"),
    ("r.sim_flagged", "yes - exceeds the thresholds", "是——超过阈值"),
    ("r.sim_not_flagged", "no - below the thresholds", "否——未达阈值"),
    ("r.sim_evidence_head", "matched row ranges (source is not copied into this report):",
     "匹配到的行段（报告不会复制源码）："),
    ("r.sim_evidence_row", "  rows {rows_a} <-> rows {rows_b}   {tokens} token(s)",
     "  行 {rows_a} <-> 行 {rows_b}   {tokens} 个 token"),
    ("r.sim_warnings", "notes: {items}", "备注：{items}"),
    ("r.sim_note", "similarity is a signal for human review, not a verdict of misconduct",
     "相似度只是供人工复核的信号，不等于作弊结论"),
    ("r.dup_head", "duplicate candidates: {count} pair(s) over {submissions} submission(s)",
     "重复嫌疑：{submissions} 份提交中找出 {count} 对"),
    ("r.dup_none", "no pair reached the thresholds", "没有配对达到阈值"),
    ("r.dup.col.score", "score", "相似度"),
    ("r.dup.col.a", "submission a", "提交 A"),
    ("r.dup.col.b", "submission b", "提交 B"),
    ("r.dup.col.user", "users", "用户"),
    ("r.dup.col.problem", "problem", "题目"),
    ("r.dup.col.evidence", "ranges", "行段数"),
    ("r.dup_more", "... {count} more pair(s) not shown (use --top or --all)",
     "……另有 {count} 对未显示（用 --top 或 --all）"),
    ("r.dup_clusters", "clusters ({count}):", "聚类（{count} 组）："),
    ("r.dup_cluster_row", "  {cid}  users={users}  files={size}  max J={jaccard}",
     "  {cid}  用户={users}  份数={size}  最高 J={jaccard}"),
    ("r.dup_warnings", "warnings:", "提示："),
    # -- progress stream (stderr, only with --progress) -----------------------
    ("r.progress", "progress: {stage} {done}/{total} ({pct}%), {elapsed}s elapsed, ~{eta}s left",
     "进度：{stage} {done}/{total}（{pct}%），已用 {elapsed}s，预计还要 ~{eta}s"),
    ("r.progress.lex", "read + fingerprint", "读取 + 指纹"),
    ("r.progress.evidence", "evidence", "取证"),
    ("r.progress.style", "style comparison", "风格对照"),
    ("r.progress_done", "progress: done, {files} file(s), {pairs} qualifying pair(s), {seconds}s",
     "进度：完成，{files} 份文件，{pairs} 对达标，用时 {seconds}s"),
    # -- audit report --------------------------------------------------------
    ("r.audit_head", "audit: {duplicates} duplicate pair(s) over {submissions} submission(s)",
     "审计：{submissions} 份提交，{duplicates} 对重复嫌疑"),
    ("r.audit_style_head", "style deviation from the user's own profile ({count} submission(s)):",
     "与用户自身风格档案的偏离（{count} 份）："),
    ("r.audit_signals_head", "external signals merged as given ({count}):",
     "外部信号按原样合并（{count} 条）："),
    ("r.audit_flags_head", "flagged for review ({count}):", "需要人工复核（{count} 份）："),
    ("r.audit_none", "  none", "  无"),
    ("r.audit_note", "flags are reasons to look, not conclusions: similarity, style drift and any "
                     "external signal all need a human to decide",
     "列出的只是「值得看一眼」的理由：相似度、风格偏离、外部信号都要人来判定"),
    ("r.audit.col.id", "submission", "提交"),
    ("r.audit.col.user", "user", "用户"),
    ("r.audit.col.findings", "findings", "问题数"),
    ("r.audit.col.severity", "worst", "最高级"),
    ("r.audit.col.rules", "rules", "涉及规则"),
    # -- findings wording ---------------------------------------------------
    ("d.indent_irregular", "indent is not a multiple of the {unit}-character unit ({actual} characters here)",
     "缩进不是 {unit} 字符单位的整数倍（此处为 {actual} 字符）"),
    ("d.width_over", "row is longer than the {limit} column limit", "该行超过 {limit} 列的宽度上限"),
    ("d.against_profile", "{label}: this file uses {actual}, the profile says {expected}",
     "{label}：本文件用的是 {actual}，档案要求 {expected}"),
    ("d.intra_file", "{label} varies: mostly {expected}, {count} row(s) use {actual}",
     "{label}存在混用：多数是 {expected}，有 {count} 行用了 {actual}"),
    ("d.current", "current", "原文"),
    ("d.formatted", "formatted", "格式化后"),
    # -- kernel errors ------------------------------------------------------
    ("e.user_required", "profile needs a non-empty user name", "档案需要一个非空的用户名"),
    ("e.no_profile", "no style profile stored for user {name!r} (in {path})",
     "{path} 中没有用户 {name} 的风格档案"),
    ("e.store_json", "profile store {path} is not valid JSON: {error}",
     "档案库 {path} 不是合法 JSON：{error}"),
    ("e.store_read", "cannot read profile store {path}: {error}", "无法读取档案库 {path}：{error}"),
    ("e.store_damaged", "profile {name} in {path} is damaged: {error}",
     "档案库 {path} 中的 {name} 已损坏：{error}"),
    ("e.store_write", "cannot write profile store {path}: {error}", "无法写入档案库 {path}：{error}"),
    ("e.store_locked", "profile store {path} is locked by another process", "档案库 {path} 被其他进程占用"),
    ("e.rename_taken", "cannot rename {old} to {new}: name taken or empty",
     "无法把 {old} 改名为 {new}：目标名为空或已存在"),
    ("e.import_json", "profile text is not valid JSON: {error}", "待导入的档案文本不是合法 JSON：{error}"),
    ("e.import_no_users", "profile file contains no users", "该档案文件里没有任何用户"),
    ("e.read_file", "cannot read {path}: {error}", "无法读取 {path}：{error}"),
    ("e.write_file", "cannot write {path}: {error}", "无法写入 {path}：{error}"),
    ("e.no_glob_match", "no files match {pattern}", "没有文件匹配 {pattern}"),
    ("e.unknown_lang", "unknown language {name!r}; try --lang with one of {options}",
     "未知语言 {name}；--lang 可选：{options}"),
    ("e.both_sources", "use either --user or --profile, not both", "--user 与 --profile 只能二选一"),
    ("e.need_profile", "a style profile is required: pass --user NAME or --profile FILE",
     "需要指定风格档案：用 --user NAME 或 --profile FILE"),
    ("e.bad_profile_json", "profile {path} is not valid JSON: {error}", "档案文件 {path} 不是合法 JSON：{error}"),
    ("e.bad_profile_path", "cannot read profile {path}: {error}", "无法读取档案文件 {path}：{error}"),
    ("e.profile_empty_file", "profile file {path} contains no users", "档案文件 {path} 里没有任何用户"),
    ("e.unknown_rules", "unknown rule(s): {rules} (see 'cf rules')", "未知规则：{rules}（见 cf rules）"),
    ("e.need_samples", "{action} needs source files to learn from", "{action} 需要用来学习的源码文件"),
    ("e.no_such_profile", "no profile named {name}", "没有名为 {name} 的档案"),
    ("e.unknown_action", "unknown profile action {action}", "未知的 profile 子命令：{action}"),
    ("e.interrupted", "interrupted", "已中断"),
    # -- formatter refusals -------------------------------------------------
    ("f.token_changed", "refused: token #{index} would change from {before} to {after}",
     "拒绝执行：第 {index} 个 token 会从 {before} 变成 {after}"),
    ("f.token_count", "refused: token count changed from {before} to {after}",
     "拒绝执行：token 数量从 {before} 变成 {after}"),
    ("f.changed", "refused: token stream changed", "拒绝执行：token 序列发生变化"),
    ("f.no_lex", "refused: the formatted text no longer lexes cleanly ({error})",
     "拒绝执行：格式化后的文本无法干净地重新分词（{error}）"),
    # -- cli command help ---------------------------------------------------
    ("h.summary", "Code style kernel: extract a developer's style, audit consistency, store profiles, reformat.",
     "代码风格内核：从样本提取风格、审计一致性、保存多人档案、格式化代码。"),
    ("h.lh.extract", "extract a style profile from code samples", "从代码样本提取风格档案"),
    ("h.lh.check", "find style inconsistencies inside and across samples", "检查样本内部与样本之间的风格不一致"),
    ("h.lh.profile", "manage stored style profiles", "管理已保存的用户风格档案"),
    ("h.lh.format", "reformat code to match a style profile", "按风格档案格式化代码"),
    ("h.lh.rules", "list the style rules the kernel understands", "列出内核识别的所有风格规则"),
    ("h.lh.languages", "list supported languages", "列出支持的语言"),
    ("h.lh.add", "create a user's profile from samples", "从样本建立某用户的风格档案"),
    ("h.lh.show", "print a stored profile", "打印某个已存档案"),
    ("h.lh.update", "merge more samples into a stored profile", "把更多样本合并进某个已存档案"),
    ("h.lh.list", "list stored profiles", "列出已存档案"),
    ("h.lh.delete", "remove a profile", "删除某个档案"),
    ("h.lh.rename", "rename a profile", "重命名某个档案"),
    ("h.lh.export", "print (or write) a profile as JSON", "导出档案 JSON（打印或写文件）"),
    ("h.lh.import", "load a profile JSON into the store", "把档案 JSON 导入档案库"),
    # -- command confirmations ---------------------------------------------
    ("c.saved", "saved profile for {user} in {path}", "已把 {user} 的档案保存到 {path}"),
    ("c.created", "created profile '{user}' from {count} sample(s), language {language}",
     "已从 {count} 个样本建立档案 '{user}'（语言：{language}）"),
    ("c.updated", "updated profile '{user}' with {count} sample(s), language {language}",
     "已把 {count} 个样本合并进档案 '{user}'（语言：{language}）"),
    ("c.replaced", "replaced profile '{user}' with {count} sample(s), language {language}",
     "已用 {count} 个样本覆盖档案 '{user}'（语言：{language}）"),
    ("c.deleted", "deleted profile '{user}'", "已删除档案 '{user}'"),
    ("c.renamed", "renamed '{old}' to '{new}'", "已把 '{old}' 改名为 '{new}'"),
    ("c.exported", "wrote {user} to {path}", "已把 {user} 的档案写入 {path}"),
    ("c.imported", "imported profile '{user}' ({count} sample(s)) into {path}",
     "已把档案 '{user}'（{count} 个样本）导入 {path}"),
    ("h.files", "source files (default: stdin)", "源码文件（留空则读标准输入）"),
    ("h.files.profile", "source files to learn from", "用于学习的源码文件"),
    ("h.lang", "force the language instead of detecting it", "指定语言（不做自动识别）"),
    ("h.store", "profile store file (default {default}, env CF_STORE)", "档案库文件（默认 {default}，可用环境变量 CF_STORE）"),
    ("h.json", "machine readable output", "输出机器可读的 JSON"),
    ("h.msg_lang", "language of messages: en or zh (env CF_LANG)", "提示语语言：en 或 zh（可用环境变量 CF_LANG）"),
    ("h.user_extract", "also save the profile under this user", "同时把档案保存为该用户"),
    ("h.replace", "replace the user's stored profile", "覆盖该用户已存的档案"),
    ("h.out", "write the profile JSON to this file", "把档案 JSON 写到该文件"),
    ("h.min_conf", "hide weakly evidenced rules", "隐藏证据薄弱的规则"),
    ("h.min_conf.format", "skip observed rules below this confidence", "置信度低于此值的已观测规则不动手"),
    ("h.show_rows", "list the rows where a rule deviates", "列出规则出现偏离的具体行号"),
    ("h.check_user", "audit against a stored profile instead of the samples' own", "对照某个已存档案检查，而不是样本自身的共识"),
    ("h.check_profile", "audit against a profile JSON file", "对照某个档案 JSON 文件检查"),
    ("h.min_evidence", "ignore rules seen fewer than N times", "忽略观测次数少于 N 次的规则"),
    ("h.max_findings", "cap printed findings (0 = no cap)", "最多打印多少条问题（0 表示不限）"),
    ("h.all", "print every finding", "打印全部问题"),
    ("h.show_rules", "also print per-rule agreement", "另外打印每条规则的一致率"),
    ("h.fail_on", "exit 1 when a finding of at least this severity exists", "存在不低于该严重度的问题时退出码为 1"),
    ("h.format_user", "use this stored profile", "使用该用户已存的档案"),
    ("h.format_profile", "use a profile JSON file", "使用指定的档案 JSON 文件"),
    ("h.write", "rewrite files in place", "就地改写文件"),
    ("h.check", "exit 1 if anything would change", "若有改动则退出码为 1"),
    ("h.diff", "show a unified diff for each change", "为每个改动输出 unified diff"),
    ("h.rules", "comma separated rule keys to apply (see 'cf rules')", "逗号分隔的规则名，只应用这些规则（见 cf rules）"),
    ("h.observed_only", "never fall back to family defaults", "不回落到语言族默认值，只用观测到的规则"),
    ("h.no_wrap", "do not split rows longer than width.limit", "不把超过 width.limit 的行继续拆分"),
    ("h.eol", "line ending style", "行尾换行符风格"),
    ("e.refused_files", "could not format {count} file(s) safely: {names}",
     "有 {count} 个文件无法安全格式化：{names}"),
    ("w.naming.*", "renaming identifiers changes the program, not its layout", "改名会改变程序本身，不属于排版"),
    ("w.semicolon.required", "adding or removing ; changes parse boundaries", "增删分号会改变语法边界（JS 的 ASI）"),
    ("w.layout.trailing_comma", "inserting a comma would change the token stream", "补尾逗号会改变 token 序列"),
    ("w.layout.wrap_operator", "moving an operator across rows is left to the author", "跨行移动运算符交给作者决定"),
    ("w.layout.single_statement_same_row", "moving statements across rows is not a layout-only edit",
     "跨行移动语句不是纯排版改动"),
    ("w.comment.*", "comment text is never rewritten", "注释内容一律不改"),
    ("w.include.*", "reordering includes can change build behaviour", "调整 include/import 顺序可能影响构建"),
    ("w.constant.*", "adding, removing or moving const changes the program, not its layout",
     "增删或移动 const 会改变程序本身，不属于排版"),
    ("w.statement.*", "turning , into ; (or back) rewrites the token stream, not the layout",
     "把逗号改成分号（或反过来）改的是 token 序列，不是排版"),
    ("h.name", "profile user name", "档案用户名"),
    # -- dup / similar ------------------------------------------------------
    ("h.lh.dup", "find duplicate or near-identical submissions across users",
     "在多用户提交中查找重复或高度相似的代码"),
    ("h.lh.audit", "combine duplicates, style deviation and external signals into one review report",
     "把查重、风格偏离与外部信号汇总成一份复核报告"),
    ("h.audit.summary", "Duplicates come from the similarity pass, style deviation from the "
                        "user's stored profile, and anything else arrives via --signals and is "
                        "merged unchanged.  Output is a review queue, never a verdict.",
     "重复来自查重，风格偏离来自该用户已存档案，其他信号通过 --signals 传入并原样合并。"
     "输出是一份待复核清单，不是结论。"),
    ("h.audit.store", "profile store to compare each user's own style against (env CF_STORE)",
     "用于比对该用户既有风格档案的档案库文件（可用环境变量 CF_STORE）"),
    ("h.audit.signals", "JSON list (or {\"signals\": [...]}) of already-computed signals, merged as given",
     "已算好的外部信号（JSON 数组或含 signals 字段的对象），按原样合并"),
    ("h.audit.fail_on", "exit 1 when the report has: any finding, a duplicate (default), or never",
     "退出码为 1 的条件：任意发现、有重复（默认）、或永不"),
    ("h.lh.similar", "compare two files for structural similarity", "比较两个文件的结构相似度"),
    ("h.dup.summary", "Compare normalised token structure: renames, whitespace and comments do not "
                      "change the score.  The report gives scores and row ranges, never source text, "
                      "and a high score is a signal for human review - not a verdict.",
     "比较的是规范化后的 token 结构：改名、空白与注释不影响分数。报告只给分数与行段，不含源码；"
     "分数高只是需要人工复核的信号，不是作弊结论。"),
    ("h.similar.summary", "One pair, no manifest, no thresholds-based exit code.",
     "只比一对文件；不需要 manifest，也不按阈值决定退出码。"),
    ("h.dup.files", "source files (default: stdin is not read; use --manifest for metadata)",
     "源码文件（不读标准输入；要带用户/题目元数据请用 --manifest）"),
    ("h.similar.files", "exactly two source files", "恰好两个源码文件"),
    ("h.dup.manifest", "JSON manifest of submissions (user, problem, path)",
     "提交清单 JSON（含 user、problem、path）"),
    ("h.dup.min_score", "jaccard threshold for reporting a pair", "判为需要复核的 Jaccard 阈值"),
    ("h.dup.min_containment", "containment threshold (partial copies)",
     "包含度阈值（用于发现部分抄袭）"),
    ("h.dup.min_shared", "minimum shared k-grams before a pair is considered",
     "少于这么多共享 k-gram 就不考虑该配对"),
    ("h.dup.min_tokens", "minimum normalised tokens for a submission", "提交至少要有这么多规范化 token"),
    ("h.dup.k", "k-gram size in normalised tokens", "以规范化 token 计的 k-gram 长度"),
    ("h.dup.window", "winnowing window width", "winnowing 取样窗口宽度"),
    ("h.dup.no_winnow", "keep every k-gram hash instead of winnowing", "不做 winnowing，保留全部 k-gram 指纹"),
    ("h.dup.keep_common", "do not drop hashes shared by over 80% of the corpus",
     "不丢弃出现在超过 80% 提交里的公共指纹（模板代码）"),
    ("h.dup.max_df", "treat a k-gram as boilerplate above this share of its problem bucket",
     "在一个题目分片内，k-gram 覆盖比例超过此值就按模板代码剔除"),
    ("h.dup.cross_user", "report only pairs from different users", "只报告跨用户的配对"),
    ("h.dup.same_user", "report only pairs from the same user", "只报告同一用户的配对"),
    ("h.dup.all_problems", "compare submissions even when their problem ids differ",
     "即使题号不同也进行比较"),
    ("h.dup.cross_language", "allow comparing files from different language families",
     "允许跨语言族比较"),
    ("h.dup.max_candidates", "cap the candidate pairs examined (warns when it cuts)",
     "限制比较的候选对数量（截断时会提示）"),
    ("h.dup.evidence", "matched row ranges listed per pair", "每对最多列出几个匹配行段"),
    ("h.dup.jobs", "spread the comparison over this many processes; 0 uses every cpu "
                    "(the report is identical either way)",
     "把比较分到这么多个进程，0 表示用满所有 cpu（两种方式的结果完全一致）"),
    ("h.dup.progress", "stream progress and an estimate of what is left to stderr",
     "把进度与剩余时间预估输出到 stderr"),
    ("h.dup.top", "maximum pairs in the text report (JSON always lists all qualifying pairs)",
     "文本报告最多列出几对（JSON 始终包含全部达标配对）"),
    ("h.dup.all", "print every qualifying pair", "打印全部达标配对"),
    ("h.dup.fail_on", "exit 1 when a pair matches this policy (default: cross-user with a manifest, "
                      "any without)",
     "按该策略决定退出码是否为 1（默认：有 manifest 时看跨用户，无 manifest 时看是否有配对）"),
    ("e.dup_no_inputs", "cf dup needs a manifest or at least one source file",
     "cf dup 需要 manifest 或至少一个源码文件"),
    ("e.similar_two", "cf similar needs exactly two files, got {count}",
     "cf similar 需要恰好两个文件，实际收到 {count} 个"),
    ("e.similarity", "duplicate check failed: {error}", "查重失败：{error}"),
    ("h.new_name", "new profile user name", "新的档案用户名"),
    ("h.profile_file", "profile JSON file to import", "要导入的档案 JSON 文件"),
    ("h.severity.none", "none", "不因此失败"),
    ("h.severity.low", "low", "低"),
    ("h.severity.medium", "medium", "中"),
    ("h.severity.high", "high", "高"),
]

# rule key -> (english label, chinese label)
_RULE_LABELS: dict[str, tuple[str, str]] = {
    "indent.type": ("indent characters", "缩进字符"),
    "indent.size": ("indent size", "缩进单位"),
    "indent.continuation": ("continuation indent", "续行缩进"),
    "indent.namespace_body": ("indent inside namespace/module bodies", "namespace/module 体是否缩进"),
    "width.limit": ("line length limit", "行宽上限"),
    "brace.style": ("opening brace placement", "左大括号位置"),
    "brace.close_same_row_branch": ("} else { on one row", "} else { 同行"),
    "brace.empty_block": ("empty block spelling", "空块写法"),
    "space.after_keyword": ("space between control keyword and (", "控制关键字与 ( 之间的空格"),
    "space.around_operators": ("spaces around binary operators", "二元运算符两侧空格"),
    "space.around_assignment": ("spaces around = in assignments", "赋值号两侧空格"),
    "space.after_comma": ("space after comma", "逗号后空格"),
    "space.before_comma": ("space before comma", "逗号前空格"),
    "space.inside_parens": ("space just inside ( )", "圆括号内侧空格"),
    "space.inside_brackets": ("space just inside [ ]", "方括号内侧空格"),
    "space.inside_braces": ("space just inside { } in literals", "字面量花括号内侧空格"),
    "space.before_call_paren": ("space before a call's (", "调用括号前空格"),
    "space.before_template_angle": ("space before a template's <", "模板左尖括号 < 前的空格"),
    "space.inside_template_angle": ("space just inside a template's < >", "模板尖括号 < > 内侧空格"),
    "space.before_semicolon": ("space before ; inside for(...)", "for(...) 内分号前空格"),
    "space.after_semicolon": ("space after ; inside for(...)", "for(...) 内分号后空格"),
    "space.around_colon_in_for": ("spacing around a meaningful colon", "有意义冒号的前后空格"),
    "space.around_pointer": ("* & attachment in declarations", "声明中 * & 的贴合方向"),
    "blank.max_in_block": ("max consecutive blank rows inside a block", "块内最大连续空行"),
    "blank.between_functions": ("blank rows between top-level definitions", "顶层定义间空行"),
    "blank.between_methods": ("blank rows between methods inside a class", "类内方法间空行"),
    "blank.after_open_brace": ("blank row right after an opening brace", "左大括号后允许空行"),
    "blank.before_close_brace": ("blank row right before a closing brace", "右大括号前允许空行"),
    "blank.file_start": ("file starts with a blank row", "文件开头空行"),
    "blank.file_end": ("blank rows at end of file", "文件结尾空行"),
    "blank.final_newline": ("file ends with a newline", "文件以换行结束"),
    "blank.trailing_whitespace": ("rows keep trailing whitespace", "行尾保留空白"),
    "comment.style": ("dominant comment syntax", "主要注释语法"),
    "comment.space_after_marker": ("space after the comment marker", "注释符后空格"),
    "comment.doc_style": ("documentation comment syntax", "文档注释写法"),
    "comment.block_ratio": ("percent of comments that are block comments", "块注释占比"),
    "quote.style": ("preferred string quote", "偏好字符串引号"),
    "semicolon.required": ("statements end with ;", "语句以分号结束"),
    "constant.marker": ("how constants are marked", "常量标记方式"),
    "constant.placement": ("const sits before or after the type", "const 与类型的先后"),
    "statement.comma_join": ("short calls joined with , instead of ;", "用逗号把短调用并成一句"),
    "layout.case_indent": ("case labels inside switch", "switch 内 case 标签缩进"),
    "layout.wrap_operator": ("operator position when a row wraps", "折行时运算符的位置"),
    "layout.args_per_row": ("argument layout in wrapped lists", "折行参数列表的排布"),
    "layout.trailing_comma": ("trailing comma in multi-line lists", "多行列表的尾逗号"),
    "layout.single_statement_same_row": ("if (x) return; kept on one row", "if (x) return; 保持同行"),
    "layout.chained_call_indent": ("indent of chained .method rows", "链式 .method 调用缩进"),
    "naming.function": ("function names", "函数命名"),
    "naming.method": ("method names", "方法命名"),
    "naming.variable": ("local variable names", "局部变量命名"),
    "naming.parameter": ("parameter names", "参数命名"),
    "naming.constant": ("constant names", "常量命名"),
    "naming.type": ("type/class names", "类型/类命名"),
    "naming.member": ("field / attribute names", "字段/属性命名"),
    "naming.macro": ("macro names", "宏命名"),
    "include.order": ("include/import ordering", "include/import 顺序"),
    "include.grouping": ("include/import grouping", "include/import 分组"),
}

_SEVERITY_ZH = {"high": "高", "medium": "中", "low": "低"}
_KIND_ZH = {"bool": "布尔", "int": "整数", "str": "枚举"}

from .profile import FEATURE_SPECS as _FEATURE_SPECS  # noqa: E402  (after the catalog, to avoid a cycle)

CATALOG: dict[str, dict[str, str]] = {key: {FALLBACK: en, "zh": zh} for key, en, zh in _MESSAGES}
FEATURE_SPECS_KEYS: tuple[str, ...] = tuple(_FEATURE_SPECS)

_locale: str | None = None


def set_locale(value: str | None) -> str:
    """Choose the message language; unknown values fall back to English."""
    global _locale
    _locale = normalize(value)
    return _locale


def get_locale() -> str:
    return _locale or normalize(os.environ.get(ENV_VAR))


def normalize(value: str | None) -> str:
    if not value:
        return FALLBACK
    text = str(value).strip().lower()
    if text.startswith("zh"):
        return "zh"
    return "en" if text in ("en", "english", "") else FALLBACK


def t(key, /, **kwargs) -> str:
    """Format a message in the active language, falling back to English then to the key.

    ``key`` is positional-only so a message may itself use a ``{key}`` placeholder.
    """
    locale = get_locale()
    entry = CATALOG.get(key if isinstance(key, str) else "")
    if entry is None:
        return key.format(**kwargs) if kwargs else key
    template = entry.get(locale) or entry[FALLBACK]
    try:
        return template.format(**kwargs)
    except (IndexError, KeyError):
        return template


def translate_value(value, kind: str | None = None) -> str:
    """Localise a value word (true/false/yes/no/severity/rule kind)."""
    locale = get_locale()
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    table_zh = {
        "true": "是", "false": "否", "yes": "是", "no": "否",
        "high": "高", "medium": "中", "low": "低",
        "space": "空格", "tab": "制表符", "mixed": "混用",
        "attach": "跟随行尾", "next": "独占一行", "n/a": "不适用",
        "aligned": "与括号对齐", "consistent": "一致",
        "indent": "缩进", "flush": "顶格", "indented": "缩进一级",
        "spaced": "两侧留空", "name": "贴合变量名", "type": "贴合类型名",
        "after": "仅冒号后留空", "before": "仅冒号前留空", "tight": "两侧不留空",
        "sorted": "已排序", "as-written": "按书写顺序", "grouped": "分组", "flat": "不分组",
        "compact": "写成 {}", "expanded": "展开写",
        "single": "单引号", "double": "双引号", "backtick": "反引号",
        "lowercase": "全小写", "UPPER_SNAKE_CASE": "大写下划线", "PascalCase": "大驼峰",
        "camelCase": "小驼峰", "snake_case": "下划线", "Pascal_Snake_Case": "大驼峰下划线",
        "mixed_case": "大小写混排",
        "none": "无", "docstring": "文档字符串", "doxygen": "Doxygen", "triple-slash": "三斜杠",
        "none (severity)": "无",
        "before-type": "类型名前", "after-type": "类型名后", "define": "#define", "enum": "枚举",
    }
    if locale != "zh":
        return text
    if kind == "severity" and text in _SEVERITY_ZH:
        return _SEVERITY_ZH[text]
    return table_zh.get(text, text)


def kind_label(kind: str) -> str:
    return _KIND_ZH.get(kind, kind) if get_locale() == "zh" else kind


def rule_label(key: str) -> str:
    """The human name of a rule in the active language (the key itself stays untranslated)."""
    pair = _RULE_LABELS.get(key)
    if pair is None:
        return key
    return pair[1] if get_locale() == "zh" else pair[0]


def has_rule_label(key: str) -> bool:
    return key in _RULE_LABELS
