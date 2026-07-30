from __future__ import annotations

import copy
from typing import Any, Dict, Optional


class GAC_DJAYA:
    name = "GAC-DJaya"
    key = "gac_djaya"

    algorithm_complete = True
    article_exact = False
    implementation = "canonical-shared-core-genetic-assisted-ring-discrete-jaya-with-cache-aware-transformations"
    reference_doi = "10.5267/j.ijiec.2015.8.004"
    discrete_reference_doi = "10.1016/j.asoc.2021.107275"
    reference_alignment = "original-jaya-best-worst-core-with-discrete-transformation-operators-ring-neighborhood-semi-steady-updates-cache-aware-probing-and-genetic-initialization"

    def run(self, base_ctx: Dict[str, Any], seed: Optional[int] = None):
        if not isinstance(base_ctx, dict):
            raise TypeError("base_ctx must be a dictionary")

        from algorithm.new_algorithm import gac_djaya_run

        ctx = copy.deepcopy(base_ctx)
        ctx["seed"] = seed
        ctx["scheme"] = self.key
        ctx["use_ranking"] = True
        ctx["use_caching"] = True
        ctx["v2i_only"] = False

        return gac_djaya_run(ctx)

    def run_joint(self, joint_ctx: Dict[str, Any], *, seed: int, tmax: int, population_size: int | None = None):
        from algorithm.new_algorithm.joint_gac_djaya import run_joint_gac_djaya

        return run_joint_gac_djaya(
            joint_ctx,
            seed=seed,
            tmax=tmax,
            population_size=population_size,
        )
