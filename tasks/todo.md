# R5.3 QA bounded ReAct Todo

## Phase 1 — Config
- [x] Add `retrieval_react_min_results` default `1`.
- [x] Add `retrieval_react_min_score` default `0.3`.
- [x] Add `retrieval_react_use_llm_judge` default `False`.
- [x] Read `PAGENT_RETRIEVAL_REACT_*` env vars.
- [x] Add fields to `to_public_dict()`.
- [x] Update `tests/test_core_config_logging.py`.
- [x] Verify: `conda run -n autoGLM pytest tests/test_core_config_logging.py`.

## Phase 2 — QA guard and constructor
- [x] Fix `top_k` None-inherit behavior.
- [x] Add ReAct threshold constructor overrides.
- [x] Add optional query rewriter injection.
- [x] Implement no-retrieve convergence for `max_steps<=0`.
- [x] Implement no-retrieve convergence for `token_budget<=0`.
- [x] Implement no-retrieve convergence for `timeout_seconds<=0`.
- [x] Verify no retriever/rewrite calls in guarded paths.

## Phase 3 — Single-step ReAct
- [x] Implement `_retrieve_loop()` for sufficient first-step path.
- [x] Implement `_get_result_score()`.
- [x] Implement `_is_evidence_sufficient()`.
- [x] Emit `qa_react_step`.
- [x] Emit `qa_react_converged`.
- [x] Keep `qa_retrieval_completed` and `qa_completed`.

## Phase 4 — Multi-step and dedupe
- [x] Implement `_rewrite_query()` with safe fallback.
- [x] Implement `_accumulate_results()` by `document_id`.
- [x] Keep higher-score duplicate evidence.
- [x] Stop by `max_steps` when still insufficient.
- [x] Store cumulative deduped evidence in dialog context.

## Phase 5 — Budget and timeout
- [x] Implement deterministic token estimate.
- [x] Stop by `token_budget` when exhausted.
- [x] Stop by `timeout` using monotonic time.
- [x] Add insufficient-evidence risk note for graceful convergence.

## Phase 6 — Regression
- [x] Update existing QA trace assertions by event name.
- [x] Add `tests/test_qa_react_loop.py` coverage.
- [x] Run targeted tests.
- [x] Run full pytest.
- [x] Run compileall.
