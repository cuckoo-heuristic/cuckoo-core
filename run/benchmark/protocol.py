from __future__ import annotations

from collections.abc import Iterable


PAPER_REPRODUCTION = "paper_reproduction"
FAIR_OPTIMIZER_COMPARISON = "fair_optimizer_comparison"
EXPERIMENT_MODES = (PAPER_REPRODUCTION, FAIR_OPTIMIZER_COMPARISON)

# DTOSC is deterministic here. The remaining paper schemes execute DCSGA's
# population search and can therefore be stopped by a common NFE budget.
POPULATION_ALGORITHMS = frozenset(
    {"dcsga", "to_v2i", "to_wo_c", "to_wo_r"}
)


def resolve_experiment_mode(
    requested_mode: str | None,
    *,
    figure: str,
    selected_algorithms: Iterable[str],
    paper_algorithms: Iterable[str],
    max_function_evaluations: int | None,
) -> str:
    """Resolve and enforce the scientific benchmark contract.

    Paper reproduction keeps the algorithm set and generation stopping rule of
    the source figure. Fair comparisons instead require one exact objective-
    evaluation budget; equal generations are not equal compute.
    """
    selected = tuple(
        dict.fromkeys(str(name).strip().lower() for name in selected_algorithms)
    )
    paper = tuple(
        dict.fromkeys(str(name).strip().lower() for name in paper_algorithms)
    )

    mode = (
        PAPER_REPRODUCTION
        if requested_mode is None
        else str(requested_mode).strip().lower()
    )
    if mode not in EXPERIMENT_MODES:
        raise ValueError(
            "experiment_mode must be 'paper_reproduction' or "
            "'fair_optimizer_comparison'"
        )

    if mode == PAPER_REPRODUCTION:
        unsupported = sorted(set(selected) - set(paper))
        if unsupported:
            raise ValueError(
                "paper_reproduction accepts only algorithms printed in the "
                f"selected source figure; unsupported: {unsupported}. Use "
                "experiment_mode='fair_optimizer_comparison' for a custom "
                "NFE-controlled comparison."
            )
        if max_function_evaluations is not None:
            raise ValueError(
                "paper_reproduction uses the paper-native generation limit. "
                "Remove max_function_evaluations, or switch to "
                "fair_optimizer_comparison."
            )
        return mode

    if figure == "all":
        raise ValueError(
            "fair_optimizer_comparison must be run one figure at a time because "
            "Figures 6-10 have different scenarios and source baselines."
        )
    if not (set(selected) & POPULATION_ALGORITHMS):
        raise ValueError(
            "fair_optimizer_comparison must include at least one population "
            "algorithm."
        )
    if max_function_evaluations is None:
        raise ValueError(
            "fair_optimizer_comparison requires max_function_evaluations so "
            "population algorithms use the same objective-call budget."
        )
    return mode
