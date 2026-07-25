from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

from parameter.services import load_params_obj

params = load_params_obj()
levy_lambda = params.levy_lambda


def nest_to_dict(nest: List[Tuple[int, int, int]]) -> Dict:
    return {i: {"provider": sp, "rank": r} for i, sp, r in nest}


def dict_to_nest(X: Dict, task_list: List[int]) -> List[Tuple[int, int, int]]:
    return [(i, X[i]["provider"], X[i]["rank"]) for i in task_list]


def hamming_distance(Xs: Dict, Xb: Dict | None, task_list: List[int]) -> int:
    if Xb is None:
        return len(task_list)
    return sum(1 for i in task_list if Xs[i]["provider"] != Xb[i]["provider"])


def levy(beta: float) -> float:
    sigma = (
        math.gamma(1 + beta)
        * math.sin(math.pi * beta / 2)
        / (math.gamma((1 + beta) / 2) * beta * (2 ** ((beta - 1) / 2)))
    ) ** (1 / beta)
    u = random.gauss(0, sigma)
    v = random.gauss(0, 1)
    return u / (abs(v) ** (1 / beta))


def normalize_levy(value: float) -> float:
    return abs(value) / (1.0 + abs(value))


def compute_L_Hm(Hm: int, task_list: List[int]) -> int:
    I = len(task_list)
    if Hm <= 0:
        return 0
    L = round(2 * Hm * normalize_levy(levy(levy_lambda)))
    return max(0, min(L, 2 * I))


def _providers(ctx) -> List[int]:
    if isinstance(ctx.get("providers"), dict):
        providers = list(ctx["providers"].keys())
    else:
        providers = list(ctx.get("sp_cpu_freq", {}).keys())

    if ctx.get("v2i_only", False):
        return [int(sp) for sp in providers if ctx.get("sp_types", {}).get(sp) == "rsu"]
    return [int(sp) for sp in providers]


def _mode(ctx, sp_id: int) -> str:
    return ctx.get(
        "sp_modes", {},
    ).get(sp_id, "v2i" if ctx.get("sp_types", {}).get(sp_id) == "rsu" else "v2v")


def random_provider(ctx, sp_list: List[int]) -> int:
    return random.choice(sp_list)


def random_provider_with_mode(ctx, sp_list: List[int], mode: str, exclude: int | None = None) -> int:
    candidates = [sp for sp in sp_list if _mode(ctx, sp) == mode and sp != exclude]

    if not candidates:
        candidates = [sp for sp in sp_list if _mode(ctx, sp) == mode]
    if not candidates:
        candidates = [sp for sp in sp_list if sp != exclude]
    if not candidates:
        return exclude if exclude is not None else random.choice(sp_list)

    return random.choice(candidates)


def rebuild_solution_state(ctx, X: Dict, task_list: List[int], sp_list: List[int]) -> None:
    z_binary = ctx["z"]["binary"]
    z_compact = ctx["z"]["compact"]
    z_binary.clear()
    counter = {sp: 0 for sp in sp_list}

    for task_id in task_list:
        sp_id = X[task_id]["provider"]

        if sp_id not in counter:
            sp_id = random_provider(ctx, sp_list)
            X[task_id]["provider"] = sp_id

        counter[sp_id] += 1
        rank = counter[sp_id]
        X[task_id]["rank"] = rank
        z_compact[task_id]["provider"] = sp_id
        z_compact[task_id]["rank"] = rank
        z_binary.setdefault(sp_id, {})
        z_binary[sp_id].setdefault(rank, {})
        z_binary[sp_id][rank][task_id] = 1


def procedure3_generate_new_solution(Xs_nest: List[Tuple[int, int, int]], Xb_nest: List[Tuple[int, int, int]] | None, ctx):
    sp_list = _providers(ctx)
    task_list = [task_id for task_id, _, _ in Xs_nest]
    Xs = nest_to_dict(Xs_nest)
    Xb = nest_to_dict(Xb_nest) if Xb_nest else None
    Xnew = {i: dict(Xs[i]) for i in task_list}

    Hm = hamming_distance(Xs, Xb, task_list)
    I = len(task_list)
    L = compute_L_Hm(Hm, task_list)
    Lquo = L // 2
    Lrem = L % 2
    transformed = set()

    if Xb is not None and Hm != I:
        diff = [i for i in task_list if Xnew[i]["provider"] != Xb[i]["provider"]]

        if Lquo != 0 and diff:
            selected = random.sample(diff, min(Lquo, len(diff)))
            for i in selected:
                Xnew[i]["provider"] = Xb[i]["provider"]
                transformed.add(i)

        if Lrem == 1:
            remaining = [
                i for i in diff
                if i not in transformed and Xnew[i]["provider"] != Xb[i]["provider"]
            ]
            if remaining:
                i = random.choice(remaining)
                target_mode = _mode(ctx, Xb[i]["provider"])
                Xnew[i]["provider"] = random_provider_with_mode(
                    ctx, sp_list, target_mode, exclude=Xnew[i]["provider"]
                )
    else:
        if Lquo != 0:
            selected = random.sample(task_list, min(Lquo, len(task_list)))
            for i in selected:
                Xnew[i]["provider"] = random_provider(ctx, sp_list)
                transformed.add(i)

        if Lrem == 1:
            remaining = [i for i in task_list if i not in transformed]
            if remaining:
                i = random.choice(remaining)
                current_mode = _mode(ctx, Xnew[i]["provider"])
                Xnew[i]["provider"] = random_provider_with_mode(
                    ctx, sp_list, current_mode, exclude=Xnew[i]["provider"]
                )

    rebuild_solution_state(ctx, Xnew, task_list, sp_list)
    return dict_to_nest(Xnew, task_list)