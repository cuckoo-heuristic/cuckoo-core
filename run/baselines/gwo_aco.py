
from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from parameter.services import load_params_obj



class GWO_ACO:
    name = "PC-ADGWO"
    key = "gwo_aco"
    article_exact = False
    implementation = "predictive-cache-guided-adaptive-discrete-gwo-aco"
    reference_doi = "10.1016/j.advengsoft.2013.12.007"

    def run(
        self,
        base_ctx: Dict[str, Any],
        seed: Optional[int] = None,
    ):
        from algorithm.gwo.core import run_gwo_aco

        ctx = copy.deepcopy(base_ctx)
        if seed is not None:
            ctx["seed"] = int(seed)
        ctx["scheme"] = self.key
        ctx["use_ranking"] = True
        ctx["use_caching"] = True
        ctx["v2i_only"] = False

        params = load_params_obj()
        tmax = max(1, int(ctx.get("tmax", 10)))
        return run_gwo_aco(
            ctx,
            population_size=int(params.S),
            iterations=tmax - 1,
            initial_discard_probability=float(params.p_discard_init),
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
        from run.benchmark.search import run_joint_gwo_aco
        return run_joint_gwo_aco(
            joint_ctx,
            algorithm=self.key,
            seed=seed,
            tmax=tmax,
            population_size=population_size,
            max_function_evaluations=max_function_evaluations,
        )
