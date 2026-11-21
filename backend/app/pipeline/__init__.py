"""Plain-Python state machine that drives a video through its stages
(NEW_PLAN.md section 5.C). No LangChain / LangGraph.

    stages.py      — stage order, stage handlers, next_stage()
    transitions.py — advance a video to its next stage and enqueue it
    runner.py      — run one stage; resume a halted video
    dispatch.py    — send Celery tasks by name (no task-module imports)
"""
