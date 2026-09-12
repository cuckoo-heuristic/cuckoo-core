from __future__ import annotations

from typing import Sequence


def _valid_providers(context, task: int) -> list[int]:
    validator = getattr(context, "valid_provider", None)
    if callable(validator):
        return list(dict.fromkeys(int(p) for p in (validator(int(task)) or [])))

    if isinstance(context, dict):
        domains = context.get("task_domains", context.get("providers", {}))
        if isinstance(domains, dict):
            values = domains.get(int(task), [])
            if isinstance(values, dict):
                values = values.keys()
            return list(dict.fromkeys(int(p) for p in (values or [])))
    return []


def _task_order(context) -> list[int]:
    order = getattr(context, "task_order", None)
    if order:
        return [int(x) for x in order]
    if isinstance(context, dict) and context.get("task_order"):
        return [int(x) for x in context["task_order"]]
    return []


def repair_solution(solution: Sequence, context):
    """Canonicalize a PSO particle and project invalid task-provider assignments.

    This deliberately matches the feasibility boundary already used by the GWO
    package.  It is not a search operator: valid assignments are preserved and
    only missing/invalid providers are projected back into the task domain.
    """
    if not solution:
        return []

    by_task: dict[int, int] = {}
    for gene in solution:
        if isinstance(gene, (tuple, list)) and len(gene) >= 2:
            by_task.setdefault(int(gene[0]), int(gene[1]))
        elif isinstance(gene, dict):
            task = gene.get("task")
            provider = gene.get("provider")
            if task is not None and provider is not None:
                by_task.setdefault(int(task), int(provider))

    order = _task_order(context) or list(by_task)
    repaired = []
    for task in order:
        providers = _valid_providers(context, int(task))
        if not providers:
            continue
        provider = int(by_task.get(int(task), providers[0]))
        if provider not in providers:
            provider = int(providers[0])
        repaired.append((int(task), int(provider), len(repaired)))

    return repaired
