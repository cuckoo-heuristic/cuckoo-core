from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from algorithm.main_dcsga import dcsga_run


class TO_WO_R:
    name = "TO_WO_R"
    key = "to_wo_r"

    def run(
        self,
        base_ctx: Dict[str, Any],
        seed: Optional[int] = None,
    ):
        if not isinstance(base_ctx, dict):
            raise TypeError("base_ctx must be a dictionary")

        ctx = copy.deepcopy(base_ctx)
        ctx["seed"] = seed
        ctx["scheme"] = self.key
        ctx["use_ranking"] = False
        ctx["use_caching"] = True
        ctx["v2i_only"] = False
        return dcsga_run(ctx)

    def run_joint(
        self,
        joint_ctx: Dict[str, Any],
        *,
        seed: int,
        tmax: int,
        population_size: int | None = None,
    ):
        from run.benchmark.search import run_joint_dcsga

        return run_joint_dcsga(
            joint_ctx,
            algorithm=self.key,
            seed=seed,
            tmax=tmax,
            population_size=population_size,
        )
