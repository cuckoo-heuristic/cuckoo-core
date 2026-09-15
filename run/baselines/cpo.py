from __future__ import annotations

from typing import Any, Dict, Optional

from parameter.services import load_params_obj
from .context import StandaloneOptimizerContext


class CPO:
    name = "CA-DCPO"
    key = "cpo"
    article_exact = False
    algorithm_complete = True
    implementation = "nfe-aware-model-guided-criticality-adaptive-discrete-cpo-v3"
    reference_doi = "10.1016/j.knosys.2023.111257"

    def run(self, base_ctx: Dict[str, Any], seed: Optional[int] = None):
        from algorithm.cpo.core import run_cpo

        ctx = StandaloneOptimizerContext(base_ctx, seed=seed)
        ctx["scheme"] = self.key
        ctx["use_ranking"] = True
        ctx["use_caching"] = True
        ctx["v2i_only"] = False
        params = load_params_obj()
        return run_cpo(
            ctx,
            population_size=int(params.S),
            iterations=max(0, int(ctx.get("tmax", 10)) - 1),
            seed=seed,
        )

    def run_joint(
        self,
        joint_ctx: Dict[str, Any],
        *,
        seed: int,
        tmax: int,
        population_size: int | None = None,
        max_function_evaluations: int | None = None,
    ):
        from run.benchmark.search import run_joint_cpo

        return run_joint_cpo(
            joint_ctx,
            algorithm=self.key,
            seed=seed,
            tmax=tmax,
            population_size=population_size,
            max_function_evaluations=max_function_evaluations,
        )
