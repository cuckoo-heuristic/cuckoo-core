from __future__ import annotations
import random
import math
from typing import Dict, List, Tuple
from parameter.services import load_params_obj, load_params_for_lib
from system.build_context import MiniSystemContextBuilder
from algorithm.update_service_cache import update_cache
from system.build_context import MiniSystemContextBuilder

params = load_params_obj()
params_lib = load_params_for_lib()

builder = MiniSystemContextBuilder(application_id=1)
ctx = builder.build_context()

z_binary = ctx["z"]["binary"]
z_compact = ctx["z"]["compact"]

sp_list = list(ctx["sp_cpu_freq"].keys())
task_list = list(ctx["cpu_cycles"].keys())
levy_lambda = params_lib["levy_lambda"]


def nest_to_dict(nest: List[Tuple[int, int, int]]) -> Dict:
    return {i: {"provider": sp, "rank": r} for (i, sp, r) in nest}


def dict_to_nest(X: Dict) -> List[Tuple[int, int, int]]:
    return [(i, X[i]["provider"], X[i]["rank"]) for i in task_list]


def hamming_distance(Xs: Dict, Xb: Dict | None) -> int:
    if Xb is None:
        return len(task_list)
    h = 0
    for i in task_list:
        if Xs[i]["provider"] != Xb[i]["provider"]:
            h += 1
    return h


def levy(beta):
    sigma = (
        math.gamma(1 + beta)
        * math.sin(math.pi * beta / 2)
        / (math.gamma((1 + beta) / 2) * beta * (2 ** ((beta - 1) / 2)))
    ) ** (1 / beta)
    u = random.gauss(0, sigma)
    v = random.gauss(0, 1)
    return u / (abs(v) ** (1 / beta))


def normalize_levy(L):
    return abs(L) / (1 + abs(L))


def compute_L_Hm(Hm):
    I = len(task_list)
    if Hm <= 0:
        return 0
    Lraw = levy(levy_lambda)
    N = normalize_levy(Lraw)
    L = round(2 * Hm * N)
    if L > 2 * I:
        L = 2 * I
    if L < 0:
        L = 0
    return L


def rebuild_binary(X):
    z_binary.clear()
    counter = {sp: 0 for sp in sp_list}

    for i in task_list:
        sp = X[i]["provider"]
        counter[sp] += 1
        r = counter[sp]
        X[i]["rank"] = r

        if sp not in z_binary:
            z_binary[sp] = {}
        if r not in z_binary[sp]:
            z_binary[sp][r] = {}
        z_binary[sp][r][i] = 1


def choose_same_mode_provider(old_sp):
    mode = ctx["sp_types"][old_sp]
    candidates = [
        sp for sp in sp_list
        if ctx["sp_types"][sp] == mode and sp != old_sp
    ]
    if not candidates:
        return old_sp
    return random.choice(candidates)


def procedure3_generate_new_solution(
    Xs_nest: List[Tuple[int, int, int]],
    Xb_nest: List[Tuple[int, int, int]] | None
):

    Xs = nest_to_dict(Xs_nest)
    Xb = nest_to_dict(Xb_nest) if Xb_nest else None

    Xnew = {i: dict(Xs[i]) for i in task_list}

    Hm = hamming_distance(Xs, Xb)
    L = compute_L_Hm(Hm)

    Lquo = L // 2
    Lrem = L % 2

    if Xb is not None and Hm != len(task_list):

        diff = [i for i in task_list if Xs[i]["provider"] != Xb[i]["provider"]]

        if Lquo > 0 and diff:
            sel = random.sample(diff, min(Lquo, len(diff)))
            for i in sel:
                Xnew[i]["provider"] = Xb[i]["provider"]

        if Lrem == 1:
            rem = [i for i in diff if Xnew[i]["provider"] != Xb[i]["provider"]]
            if rem:
                i = random.choice(rem)
                Xnew[i]["provider"] = Xb[i]["provider"]

    else:

        if Lquo > 0:
            sel = random.sample(task_list, min(Lquo, len(task_list)))
            for i in sel:
                old_sp = Xnew[i]["provider"]
                Xnew[i]["provider"] = choose_same_mode_provider(old_sp)

        if Lrem == 1:
            i = random.choice(task_list)
            old_sp = Xnew[i]["provider"]
            Xnew[i]["provider"] = choose_same_mode_provider(old_sp)

    rebuild_binary(Xnew)

    for i in task_list:
        update_cache(ctx, Xnew[i]["provider"], i, 0)

    return dict_to_nest(Xnew)
# hello