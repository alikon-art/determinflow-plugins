#!/usr/bin/env python3
"""
AI 文本检测脚本 — 调 AI Detect Gateway 的 humanize-chinese 引擎，
提取 issues + segment_analysis（句/词/段三级分析），注入自审 agent 首条消息。

用法:
  python ai_detect.py --body-file story/0001/chapter.md
  python ai_detect.py --body-file story/0001/chapter.md --output cache/ai_issues.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

GATEWAY_URL = os.environ.get(
    "AI_DETECT_GATEWAY_URL",
    "http://host.docker.internal:8002/detect",
)

# ── 问题类型中文标签 ──────────────────────────────────────

ISSUE_TYPE_LABELS: dict[str, str] = {
    # critical
    "three_part_structure": "三段式套路",
    "mechanical_connectors": "机械连接词",
    "empty_grand_words": "空洞宏大词",
    # high
    "ai_high_freq_words": "AI高频词",
    "filler_phrases": "套话/废话",
    "balanced_arguments": "过度两面论",
    "template_sentences": "模板句式",
    # medium
    "hedging_language": "过度谨慎用语",
    "list_addiction": "列举上瘾",
    "punctuation_overuse": "标点过度",
    "excessive_rhetoric": "修辞过多（对偶/排比）",
    # style
    "uniform_paragraphs": "段落过于均匀",
    "low_burstiness": "句式节奏单一",
    "emotional_flatness": "情感表达平淡",
    "repetitive_starters": "句首重复",
    "low_entropy": "信息熵偏低",
    # statistical
    "stat_low_perplexity": "困惑度异常低",
    "stat_low_burstiness": "困惑度变化均匀",
    "stat_uniform_entropy": "段落熵值均匀",
    "stat_low_surprisal_skew": "困惑度偏度低",
    "stat_low_surprisal_kurt": "困惑度峰度低",
    "stat_high_top10_bucket": "高频续接占比高",
    "stat_low_sentence_length_cv": "句长过于均匀",
    "stat_low_short_sentence_fraction": "缺少短句",
    "stat_low_comma_density": "逗号停顿偏少",
    "stat_high_transition_density": "过渡词过密",
    "stat_high_curvature": "局部曲率高",
    "stat_low_binoculars_diff": "双ngram对齐度高",
    "stat_low_char_mattr": "字符多样性偏低",
    "stat_low_para_sent_len_cv": "段内句长均匀",
}

SEVERITY_MARKERS: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "style": "⚪",
    "statistical": "📊",
}

SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "style": 3,
    "statistical": 4,
}

# ── 核心逻辑 ──────────────────────────────────────────────


def detect_text(text: str) -> dict:
    """调用 gateway，返回 humanize-chinese 引擎的原始结果"""
    payload = json.dumps({
        "text": text,
        "engines": ["humanize-chinese"],
    }).encode("utf-8")

    req = urllib.request.Request(
        GATEWAY_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")

    # 解析 SSE 流：找 humanize-chinese 的 engine 事件
    engine_result = None
    done_result = None
    for line in body.split("\n"):
        if not line.startswith("data: "):
            continue
        data = json.loads(line[6:])
        engine = data.get("engine", "")
        if engine == "humanize-chinese":
            engine_result = data
        elif engine == "" and "verdict" in data:
            done_result = data

    if engine_result is None:
        return {"error": "未在 SSE 响应中找到 humanize-chinese 引擎结果"}

    return engine_result


def extract_all_issues(result: dict) -> list[dict]:
    """从引擎结果中提取所有级别的问题，按严重度排序"""
    raw = result.get("raw", {})
    issues = raw.get("issues", {})

    out: list[dict] = []
    for issue_type, items in issues.items():
        for item in items:
            out.append({
                "type": issue_type,
                "severity": item.get("severity", ""),
                "text": item.get("text", ""),
                "count": item.get("count", 0),
            })

    out.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 99))
    return out


def format_for_agent(
    issues: list[dict],
    score: float,
    level: str,
    worst_sentences: list[dict],
    segment_analysis: dict | None = None,
) -> str:
    """将检测结果格式化为自审 agent 可用的提示文本，含句/词/段三级分析"""

    total = len(issues)
    worst_count = len(worst_sentences)
    seg = segment_analysis or {}

    has_seg = bool(
        seg.get("sentence_scores")
        or seg.get("paragraph_scores")
        or seg.get("predictability", {}).get("tokens")
    )

    # 无问题且无逐句分析 → 简短确认
    if total == 0 and worst_count == 0 and not has_seg:
        return (
            f"（外部检测引擎综合评分 {score:.0%}，等级 {level}，"
            f"未发现机械性问题）"
        )

    lines: list[str] = []
    lines.append(
        f"「外部 AI 检测引擎报告」综合评分 {score:.0%}，等级 {level}，"
        f"共 {total} 项问题。自审时逐条核验：\n"
    )

    # ── 一、issues 按严重度 ──
    if issues:
        last_severity = None
        for issue in issues:
            sev = issue["severity"]
            if sev != last_severity:
                last_severity = sev
                lines.append(f"## {_severity_group_label(sev)}")
            sev_mark = SEVERITY_MARKERS.get(sev, "⚪")
            type_label = ISSUE_TYPE_LABELS.get(issue["type"], issue["type"])
            detail = issue["text"]
            if issue.get("count") and issue["count"] > 1:
                detail += f"（出现 {issue['count']} 次）"
            lines.append(f"- {sev_mark} {type_label}：{detail}")

    # ── 二、逐句分析 ──
    sentence_scores = seg.get("sentence_scores", [])
    if sentence_scores:
        suspicious = [s for s in sentence_scores if s.get("score", 0) > 0]
        if suspicious:
            lines.append("")
            lines.append("## 🔍 逐句分析（ai-score 越高越可疑）")
            lines.append("")
            for s in suspicious:
                _fmt_sentence(s, lines)

    # ── 三、段落分析 ──
    paragraph_scores = seg.get("paragraph_scores", [])
    if paragraph_scores:
        suspicious_paras = [p for p in paragraph_scores if p.get("score", 0) > 0]
        if suspicious_paras:
            lines.append("")
            lines.append("## 📝 段落分析")
            lines.append("")
            for p in suspicious_paras:
                _fmt_paragraph(p, lines)

    # ── 四、按指标聚合 ──
    metric_targets = seg.get("metric_targets", {})
    if metric_targets:
        lines.append("")
        lines.append("## 🎯 按指标类型聚合")
        lines.append("")
        for metric, entries in metric_targets.items():
            if not entries:
                continue
            metric_label = _metric_label(metric)
            lines.append(f"### {metric_label}")
            for entry in entries[:6]:  # 每种指标最多 6 条
                etype = entry.get("type", "")
                idx = entry.get("index", "?")
                escore = entry.get("score", 0)
                etext = entry.get("text", "")
                ereasons = "；".join(entry.get("reasons", []))
                esugg = entry.get("suggestion", "")
                tag = "段" if etype == "paragraph" else "句"
                lines.append(f"- [{tag}{idx} score={escore}] {etext}")
                if ereasons:
                    lines.append(f"  → {ereasons}")
                if esugg:
                    lines.append(f"  💡 {esugg}")
            lines.append("")

    # ── 五、可预测词清单 ──
    pred = seg.get("predictability", {})
    pred_tokens = pred.get("tokens", [])
    if pred_tokens:
        # 只列 score > 0 的（即被标记为可疑的）
        flagged = [t for t in pred_tokens if t.get("score", 0) > 0]
        if flagged:
            lines.append("## 🔑 可预测词清单（按 AI 可疑度排序）")
            lines.append("")
            flagged.sort(key=lambda t: t.get("score", 0), reverse=True)
            for t in flagged[:15]:  # 最多 15 个
                tword = t.get("text", "")
                tscore = t.get("score", 0)
                treason = t.get("reason", "")
                tctx = t.get("context", "")
                lines.append(f"- 「{tword}」（score={tscore}）")
                if treason:
                    lines.append(f"  → {treason}")
                # 逐字符预测详情
                char_details = t.get("char_details", [])
                if char_details:
                    for cd in char_details:
                        ch = cd.get("char", "")
                        rank = cd.get("rank", "?")
                        bucket = cd.get("bucket", "")
                        predicted = cd.get("predicted_next_chars", [])
                        lines.append(f"  🔤 字符「{ch}」→ rank={rank}（{bucket}），模型预测的 top 替代：{' / '.join(predicted[:8])}")
                if tctx:
                    ctx_short = tctx if len(tctx) <= 80 else tctx[:77] + "..."
                    lines.append(f"  …{ctx_short}…")
            lines.append("")

    # ── 六、最可疑句子（旧字段，兼容） ──
    if worst_sentences:
        lines.append("## 引擎标记的可疑句子（旧）")
        for ws in worst_sentences[:5]:
            reasons = "、".join(ws.get("reasons", []))
            lines.append(f"- 「{ws['sentence']}」")
            if reasons:
                lines.append(f"  → {reasons}")

    return "\n".join(lines)


def _fmt_sentence(s: dict, lines: list[str]) -> None:
    """格式化单句分析"""
    idx = s.get("index", "?")
    sscore = s.get("score", 0)
    text = s.get("text", "")
    reasons = s.get("reasons", [])
    sugg = s.get("suggestion", "")

    lines.append(f"### 句{idx}（score={sscore}）「{text}」")
    if reasons:
        lines.append(f"→ {'；'.join(reasons)}")
    if sugg:
        lines.append(f"💡 {sugg}")

    # 句内可预测词
    ptokens = s.get("predictability_tokens", [])
    if ptokens:
        for pt in ptokens:
            pword = pt.get("text", "")
            pscore = pt.get("score", 0)
            if pscore > 0:
                lines.append(f"  ⚡ 可疑词「{pword}」（score={pscore}）")

    # 修辞模式
    rhetoric = s.get("rhetoric_patterns", [])
    if rhetoric:
        patterns = [r.get("reason", r.get("type", str(r))) for r in rhetoric]
        lines.append(f"  📐 修辞模式：{'; '.join(patterns)}")

    lines.append("")


def _fmt_paragraph(p: dict, lines: list[str]) -> None:
    """格式化段落分析"""
    idx = p.get("index", "?")
    pscore = p.get("score", 0)
    cn_len = p.get("cn_len", 0)
    sent_cnt = p.get("sentence_count", 0)
    reasons = p.get("reasons", [])
    sugg = p.get("suggestion", "")

    lines.append(f"### 段{idx}（score={pscore}，{cn_len}字，{sent_cnt}句）")
    if reasons:
        lines.append(f"→ {'；'.join(reasons)}")
    if sugg:
        lines.append(f"💡 {sugg}")

    ptokens = p.get("predictability_tokens", [])
    if ptokens:
        for pt in ptokens:
            pword = pt.get("text", "")
            pscore = pt.get("score", 0)
            if pscore > 0:
                lines.append(f"  ⚡ 可疑词「{pword}」（score={pscore}）")

    lines.append("")


def _metric_label(metric: str) -> str:
    """指标名 → 中文标签"""
    return {
        "gltr_top10_frac": "高频续接占比",
        "predictability": "词级可预测性",
        "sent_len_cv": "句长变异系数",
        "sent_len_short_frac": "短句占比",
        "sent_len_long_frac": "长句占比",
        "sent_len_equal_mid_frac": "中等句长占比",
        "punct_comma_density": "逗号密度",
        "punct_density": "标点密度",
        "trans_density": "过渡词密度",
        "curv_mean": "局部曲率",
        "bino_lp_diff": "双ngram对齐度",
        "uni_tri_ratio": "字符多样性",
        "para_sent_len_cv_avg": "段内句长变异",
        "paragraph_length_cv": "段落长度变异",
        "cross_para_3gram_repeat": "跨段3gram重复",
        "wiki_vs_human": "维基vs人类",
        "wiki_vs_primary": "维基vs基础",
        "news_vs_human": "新闻vs人类",
    }.get(metric, metric)


def _severity_group_label(sev: str) -> str:
    return {
        "critical": "🔴 严重",
        "high": "🟠 高",
        "medium": "🟡 中",
        "style": "⚪ 风格",
        "statistical": "📊 统计",
    }.get(sev, sev)


# ── 入口 ──────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI 文本检测 — 提取严重问题供自审 agent 使用"
    )
    parser.add_argument(
        "--body-file",
        required=True,
        help="章节正文文件路径",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径（默认 stdout）",
    )
    parser.add_argument(
        "--format",
        default="agent",
        choices=["agent", "json"],
        help="输出格式：agent=自审提示文本, json=结构化数据",
    )
    parser.add_argument(
        "--gateway-url",
        default=GATEWAY_URL,
        help=f"Gateway 地址（默认 {GATEWAY_URL}）",
    )
    args = parser.parse_args()

    # 1. 读章节正文
    try:
        with open(args.body_file, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        msg = f"（AI 检测跳过：章节文件不存在 {args.body_file}）"
        _emit(msg, args)
        return
    except Exception as e:
        msg = f"（AI 检测跳过：读取章节文件失败 {e}）"
        _emit(msg, args)
        return

    if len(text.strip()) < 10:
        msg = "（AI 检测跳过：文本太短）"
        _emit(msg, args)
        return

    # 2. 调 gateway
    try:
        engine_result = detect_text(text)
    except urllib.error.URLError as e:
        msg = f"（AI 检测不可用：无法连接 Gateway {args.gateway_url} — {e.reason}）"
        _emit(msg, args)
        return
    except Exception as e:
        msg = f"（AI 检测不可用：{e}）"
        _emit(msg, args)
        return

    # 3. 解析结果
    if "error" in engine_result:
        msg = f"（AI 检测引擎错误：{engine_result['error']}）"
        _emit(msg, args)
        return

    issues = extract_all_issues(engine_result)
    raw = engine_result.get("raw", {})
    score = engine_result.get("score", 0)
    level = raw.get("level", "unknown")
    worst_sentences = raw.get("worst_sentences", [])
    segment_analysis = raw.get("segment_analysis", {})

    # 4. 格式化输出
    if args.format == "json":
        output = json.dumps(
            {
                "score": score,
                "level": level,
                "total_issues": raw.get("total_issues", 0),
                "all_issues": issues,
                "worst_sentences": worst_sentences,
                "segment_analysis": segment_analysis,
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        output = format_for_agent(issues, score, level, worst_sentences, segment_analysis)

    _emit(output, args)


def _emit(text: str, args: argparse.Namespace) -> None:
    if args.output:
        import os
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        # 始终写到指定路径（供下游节点读取）
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        # 同时保存版本化副本（不覆盖历史）
        archive = _versioned_path(args.output)
        if archive != args.output:
            with open(archive, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"[OK] AI 检测完成 → {args.output}（副本：{archive}）")
        else:
            print(f"[OK] AI 检测完成 → {args.output}")
    else:
        print(text)


def _versioned_path(filepath: str) -> str:
    """如果文件已存在，自动追加版本号后缀（ai_issues.txt → ai_issues_v2.txt）。"""
    import os
    if not os.path.exists(filepath):
        return filepath
    base, ext = os.path.splitext(filepath)
    v = 2
    while os.path.exists(f"{base}_v{v}{ext}"):
        v += 1
    return f"{base}_v{v}{ext}"


if __name__ == "__main__":
    main()
