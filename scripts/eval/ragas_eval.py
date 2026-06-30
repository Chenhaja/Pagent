# eval/ragas_eval.py
"""
Pagent 办理流程类评测集 → Ragas 评估
与 tests/eval/golden_qa.jsonl 的新 schema 一一对应：
  {"question", "expected_item", "expected_section", "expected_locators", "intent"}
gold 直接用 (expected_item, expected_section) 精确匹配 load_chunks 的 (item_name, section)，
不再做归一化 / 剥序号 / 费用→流程 兜底。

依赖: pip install ragas langchain-openai pandas
用法:
  python -m eval.ragas_eval                       # 检索指标(默认 --no-generation)
  python -m eval.ragas_eval --generate            # 额外评 Faithfulness/ResponseRelevancy
  python -m eval.ragas_eval --top-k 5 --limit 10
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import get_settings
from app.tools.retrieval import build_retriever
from scripts.ingest_knowledge import load_chunks

# ---------- 1. 读测试集 ----------
def load_eval(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

# ---------- 2. 构建 gold 映射 (item_name, section) -> [content] ----------
def build_gold_map(knowledge_root: Path) -> dict[tuple[str, str], list[str]]:
    gold: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ch in load_chunks(str(knowledge_root)):
        if ch.doc_type != "procedure":
            continue
        # 与测试集逐字对应：item_name 带序号(如 一、专利申请)，section 带序号(如 （四）办理流程)
        gold[(ch.item_name, ch.section)].append(ch.content)
    return gold

def resolve_reference_contexts(
    item: str, section: str, gold: dict[tuple[str, str], list[str]]
) -> list[str]:
    return gold.get((item, section), [])

# ---------- 3. 组装 Ragas 样本 ----------
def build_samples(
    eval_rows: list[dict[str, Any]],
    gold: dict[tuple[str, str], list[str]],
    retriever,
    top_k: int,
    generate: bool,
):
    from ragas.dataset_schema import SingleTurnSample

    qa_node = None
    if generate:
        from app.nodes.qa import QANode
        from app.models.schemas import WorkflowState  # 若路径不同按实际调整
        qa_node = (QANode(), WorkflowState)

    samples: list[SingleTurnSample] = []
    meta: list[dict[str, Any]] = []

    for row in eval_rows:
        q = row["question"]
        item = row.get("expected_item", "")
        section = row.get("expected_section", "")
        expected_locators = row.get("expected_locators", [])

        # 3.1 检索
        results = retriever.search(q, top_k=top_k)
        retrieved_contexts = [r.content for r in results]
        retrieved_locators = [
            (r.provenance or {}).get("locator", "") for r in results
        ]

        # 3.2 gold
        reference_contexts = resolve_reference_contexts(item, section, gold)
        has_gold = bool(reference_contexts)

        # 3.3 事项级 / 小节级 命中（自查用，Ragas 不读）
        item_hit = any(item and item in loc for loc in retrieved_locators)
        section_hit = any(loc in expected_locators for loc in retrieved_locators)

        # 3.4 生成答案（可选）
        response = ""
        if qa_node is not None:
            node, StateCls = qa_node
            state = StateCls(raw_input=q)
            node.run(state)
            response = (state.dialog_context.get("qa_result") or {}).get("answer", "")

        samples.append(
            SingleTurnSample(
                user_input=q,
                retrieved_contexts=retrieved_contexts,
                response=response or "",
                reference_contexts=reference_contexts or [],
            )
        )
        meta.append(
            {
                "intent": row.get("intent", ""),
                "expected_item": item,
                "expected_section": section,
                "has_gold": has_gold,
                "item_hit": item_hit,
                "section_hit": section_hit,
                "retrieved_locators": " | ".join(retrieved_locators),
            }
        )
    return samples, meta

# ---------- 4. 评判模型 ----------
def build_judges(timeout: float):
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    s = get_settings()
    judge_model = __import__("os").environ.get("PAGENT_EVAL_JUDGE_MODEL", s.llm_model)
    llm = LangchainLLMWrapper(
        ChatOpenAI(
            model=judge_model,
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            temperature=0,
            timeout=timeout,
            max_retries=1,
        )
    )
    emb = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(
            model=s.embedding_model,
            base_url=s.embedding_base_url,
            api_key=s.embedding_api_key,
            timeout=timeout,
            max_retries=1,
        )
    )
    return llm, emb

# ---------- 5. main ----------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default="test/eval/golden_qa.jsonl")
    ap.add_argument("--knowledge", default="knowledge/")
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--out", default="eval/ragas_report.csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0, help="评审 LLM/embedding 单次请求超时秒数")
    ap.add_argument("--max-workers", type=int, default=1, help="Ragas 评估并发数")
    ap.add_argument(
        "--generate",
        action="store_true",
        help="额外评 Faithfulness/ResponseRelevancy（需要跑通 QANode 生成）",
    )
    args = ap.parse_args()

    settings = get_settings()
    top_k = args.top_k or settings.retrieval_top_k

    eval_rows = load_eval(Path(args.eval))
    # 只评办理流程类（指南）；如要全量评就去掉这行
    eval_rows = [r for r in eval_rows if r.get("intent") == "办理流程"]
    if args.limit:
        eval_rows = eval_rows[: args.limit]

    gold = build_gold_map(Path(args.knowledge))
    retriever = build_retriever(settings)

    samples, meta = build_samples(eval_rows, gold, retriever, top_k, args.generate)

    # 5.1 指标
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import (
        NonLLMContextPrecisionWithReference,
        NonLLMContextRecall,
    )

    metrics = [NonLLMContextRecall(), NonLLMContextPrecisionWithReference()]
    llm = emb = None
    if args.generate:
        from ragas.metrics import Faithfulness, ResponseRelevancy

        metrics += [Faithfulness(), ResponseRelevancy(strictness=1)]
        llm, emb = build_judges(args.timeout)

    dataset = EvaluationDataset(samples=samples)
    evaluate_kwargs = {"dataset": dataset, "metrics": metrics, "llm": llm, "embeddings": emb}
    try:
        from ragas.run_config import RunConfig

        evaluate_kwargs["run_config"] = RunConfig(timeout=args.timeout, max_workers=args.max_workers)
    except Exception:
        pass
    result = evaluate(**evaluate_kwargs)

    # 5.2 合并元数据 + 落盘
    df = result.to_pandas()
    meta_df = pd.DataFrame(meta)
    report = pd.concat([df.reset_index(drop=True), meta_df], axis=1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(args.out, index=False, encoding="utf-8-sig")

    # 5.3 控制台汇总
    metric_cols = [c for c in df.columns if c not in {
        "user_input", "retrieved_contexts", "reference_contexts", "response"
    }]
    print(f"\n样本数: {len(report)}  has_gold: {int(report['has_gold'].sum())}/{len(report)}")
    print(f"事项级命中率: {report['item_hit'].mean():.3f}   小节级命中率: {report['section_hit'].mean():.3f}")
    print("\n总体指标:")
    print(report[metric_cols].mean(numeric_only=True).round(4).to_string())
    print("\n按 expected_section:")
    print(report.groupby("expected_section")[metric_cols].mean(numeric_only=True).round(4).to_string())
    print(f"\n报告已写入 {args.out}")

if __name__ == "__main__":
    main()