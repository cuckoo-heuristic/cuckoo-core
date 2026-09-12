
from __future__ import annotations

from collections import defaultdict
import math

"""
GPC memory / repair boundary.

This file must use the canonical repair logic already used by the benchmark
pipeline. The benchmark context already exposes repair through the same
mechanism used by GWO/PSO, therefore GPC should not import a non-existing
function from dcsga_core.
"""


def repair_solution(solution, context):
    if hasattr(context, "repair_solution") and callable(context.repair_solution):
        repaired = context.repair_solution(solution)
    else:
        # Fallback to the existing validated repair implementation.
        from algorithm.gwo.memory import repair_solution as gwo_repair
        repaired = gwo_repair(solution, context)

    if repaired is None:
        raise RuntimeError(
            "GPC repair_solution returned None"
        )

    return repaired


def _context_value(context, key, default=None):
    if isinstance(context, dict):
        return context.get(key, default)
    return getattr(context, key, default)


class ServiceAffinityMemory:
    """Bounded accepted-move memory; guidance only, never a fitness bonus."""

    def __init__(self, context, *, weight=0.65, evaporation=0.08):
        self.weight = max(0.0, min(1.0, float(weight)))
        self.evaporation = max(0.0, min(0.95, float(evaporation)))
        self.task_types = _context_value(context, "task_type_ids", {}) or {}
        self.task_provider = defaultdict(float)
        self.service_provider = defaultdict(float)
        self.successful_updates = 0
        self.changed_coordinates_rewarded = 0

    def begin_generation(self):
        factor = 1.0 - self.evaporation
        for table in (self.task_provider, self.service_provider):
            for key in list(table):
                table[key] *= factor
                if table[key] < 1e-10:
                    del table[key]

    def _task_type(self, task):
        value = self.task_types.get(int(task), self.task_types.get(str(int(task))))
        return None if value is None else int(value)

    def reward(self, solution, gain, *, reference):
        gain = max(0.0, float(gain))
        if gain <= 0.0:
            return False
        before = {int(g[0]): int(g[1]) for g in reference or [] if len(g) >= 2}
        changed = [
            (int(g[0]), int(g[1])) for g in solution or []
            if len(g) >= 2 and before.get(int(g[0])) != int(g[1])
        ]
        if not changed:
            return False
        deposit = min(2.0, 0.25 + math.log1p(gain)) / float(len(changed))
        for task, provider in changed:
            self.task_provider[(task, provider)] += deposit
            task_type = self._task_type(task)
            if task_type is not None:
                self.service_provider[(task_type, provider)] += deposit
        self.successful_updates += 1
        self.changed_coordinates_rewarded += len(changed)
        return True

    @staticmethod
    def _normalize(values):
        lo, hi = (min(values.values()), max(values.values())) if values else (0.0, 0.0)
        if hi <= lo:
            return {key: (1.0 if hi > 0.0 else 0.0) for key in values}
        return {key: (value - lo) / (hi - lo) for key, value in values.items()}

    def provider_scores(self, task, providers):
        providers = list(dict.fromkeys(int(value) for value in providers))
        task = int(task)
        direct = self._normalize(
            {p: self.task_provider.get((task, p), 0.0) for p in providers}
        )
        task_type = self._task_type(task)
        shared = self._normalize(
            {p: self.service_provider.get((task_type, p), 0.0) if task_type is not None else 0.0 for p in providers}
        )
        return {p: self.weight * direct.get(p, 0.0) + (1.0 - self.weight) * shared.get(p, 0.0) for p in providers}

    def profile(self):
        return {
            "service_memory_successful_updates": int(self.successful_updates),
            "service_memory_changed_coordinates": int(self.changed_coordinates_rewarded),
            "service_memory_task_entries": int(len(self.task_provider)),
            "service_memory_service_entries": int(len(self.service_provider)),
        }
