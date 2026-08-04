from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from uuid import uuid4

from django.conf import settings

from dag.models import ApplicationType, Task
from monarch_pylib.model import transmission
from object.models import RSU, ServiceProvider, Vehicle
from parameter.services import load_params_obj

from .context import BenchmarkSnapshot, build_synthetic_joint_context
from .runner import run_joint_context_benchmark


ARTICLE_DOI = "10.1109/TVT.2025.3540639"
DEADLINES_MS = (30, 40, 50, 60, 70, 80, 90, 100)
VEHICLE_COUNTS = (52, 56, 60, 64, 68, 72, 76)
VEHICLE_SPEEDS_KMH = (75, 80, 85, 90, 95, 100, 105)
MEC_CAPACITIES_GHZ = (30, 40, 50, 60, 70, 80)
ALGORITHM_LABELS = {
    "dcsga": "DCSGA",
    "dtosc": "DTOSC",
    "to_v2i": "TO-V2I",
    "to_wo_c": "TO-w.o.-C",
    "to_wo_r": "TO-w.o.-R",
}
PAPER_FIGURE_ALGORITHMS = {
    "figure_6": ("dcsga",),
    "figure_7": ("dcsga", "dtosc", "to_v2i", "to_wo_c", "to_wo_r"),
    "figure_8": ("dcsga", "to_wo_c", "to_wo_r"),
    "figure_9": ("dcsga", "dtosc"),
    "figure_10": ("dcsga", "dtosc"),
}

FIGURE_ALGORITHMS = dict(PAPER_FIGURE_ALGORITHMS)



def _close(actual: float, expected: float, tolerance: float = 1e-9) -> bool:
    limit = max(1e-30, abs(float(expected)) * tolerance)
    return abs(float(actual) - float(expected)) <= limit


def _validate_paper_parameters() -> None:
    params = load_params_obj()
    expected = {
        "B": 20.0,
        "delta2": -114.0,
        "Y_v2i": 3.76,
        "Y_v2v": 1.8,
        "sigma_v2i": 8.0,
        "sigma_v2v": 3.0,
        "h_rsu": 5.0,
        "h_vehicle": 1.5,
        "G_rsu": 8.0,
        "G_vehicle": 3.0,
        "levy_lambda": 1.5,
        "p_discard_init": 0.2,
        "S": 50.0,
        "k": 1e-25,
        "cell_radius_rsu": 250.0,
        "rec_noi_rsu": 5.0,
        "rec_noi_vehicle": 9.0,
        "pmax_vehicle": 23.0,
        "pmax_rsu": 30.0,
        "fmax_vehicle": 3.0,
        "fmax_rsu": 50.0,
        "vehicle_speed_min_kmh": 60.0,
        "vehicle_speed_max_kmh": 80.0,
        "application_rate_per_second": 10.0,
    }
    mismatches = []
    for name, expected_value in expected.items():
        actual_value = float(getattr(params, name))
        if not _close(actual_value, expected_value):
            mismatches.append(
                f"{name}={actual_value} (paper value: {expected_value})"
            )
    if mismatches:
        raise ValueError(
            "Paper experiment parameters do not match Table III: "
            + "; ".join(mismatches)
        )


def _validate_paper_data(
    vehicles: Sequence[Vehicle],
    rsus: Sequence[RSU],
    application_types: Dict[int, ApplicationType],
) -> None:
    expected_cache_bytes = 625000000
    invalid_vehicles = [
        int(vehicle.id)
        for vehicle in vehicles
        if int(vehicle.cpu_capacity) != 3000000000
        or int(vehicle.cache_capacity) != expected_cache_bytes
    ]
    if invalid_vehicles:
        raise ValueError(
            f"Vehicles do not match Table III CPU/cache values: {invalid_vehicles}"
        )
    invalid_rsus = [
        int(rsu.id)
        for rsu in rsus
        if int(rsu.cpu_capacity) != 50000000000
        or int(rsu.cache_capacity) != expected_cache_bytes
    ]
    if invalid_rsus:
        raise ValueError(
            f"RSUs do not match Table III CPU/cache values: {invalid_rsus}"
        )
    task_rows = list(
        Task.objects.filter(
            application_type_id_id__in=[
                application_type.id
                for application_type in application_types.values()
            ]
        )
        .select_related("task_type_id")
        .order_by("application_type_id_id", "id")
    )
    tasks_by_type: Dict[int, List[Task]] = {}
    for task in task_rows:
        tasks_by_type.setdefault(int(task.application_type_id_id), []).append(task)
    for deadline_ms, application_type in application_types.items():
        tasks = tasks_by_type.get(int(application_type.id), [])
        if len(tasks) != 10:
            raise ValueError(
                f"Application type {application_type.id} for {deadline_ms} ms must have 10 tasks"
            )
        for task in tasks:
            cycles = int(task.workload_cycles)
            if cycles < 10000000 or cycles > 30000000:
                raise ValueError(
                    f"Task {task.id} workload is outside the Table III range"
                )
            task_type = task.task_type_id
            if task_type is None:
                raise ValueError(f"Task {task.id} has no task type")
            snapshot = task.initial_snapshot or {}
            task_type_snapshot = task_type.initial_snapshot or {}
            output_bits = snapshot.get(
                "output_size_bits",
                task_type_snapshot.get("communication_data_bits"),
            )
            service_bits = task_type_snapshot.get(
                "service_environment_size_bits",
                int(task_type.size) * 8,
            )
            if output_bits is None or not 100000 <= int(output_bits) <= 300000:
                raise ValueError(
                    f"Task {task.id} communication data is outside the Table III range"
                )
            if not 500000000 <= int(service_bits) <= 1000000000:
                raise ValueError(
                    f"Task type {task_type.id} service size is outside the Table III range"
                )

def _normalize_figure(value: str) -> str:
    compact = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "6": "figure_6",
        "7": "figure_7",
        "8": "figure_8",
        "9": "figure_9",
        "10": "figure_10",
        "fig6": "figure_6",
        "fig7": "figure_7",
        "fig8": "figure_8",
        "fig9": "figure_9",
        "fig10": "figure_10",
        "*": "all",
        "all_figures": "all",
    }
    compact = aliases.get(compact, compact)
    if compact == "all":
        return compact
    if compact not in FIGURE_ALGORITHMS:
        raise ValueError(f"Unsupported paper figure: {value}")
    return compact


def _stats(values: Sequence[float]) -> Dict[str, float]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": float(mean(numbers)),
        "std": float(stdev(numbers)) if len(numbers) > 1 else 0.0,
        "min": float(min(numbers)),
        "max": float(max(numbers)),
    }


def _load_paper_environment() -> Tuple[List[Vehicle], List[RSU], Dict[int, ApplicationType]]:
    vehicles = list(
        Vehicle.objects.filter(is_mission=True).order_by("id")
    )
    if len(vehicles) < 76:
        raise ValueError(
            f"The paper experiments require at least 76 mission vehicles; found {len(vehicles)}"
        )
    vehicles = vehicles[:76]
    rsus = list(RSU.objects.order_by("id")[:5])
    if len(rsus) != 5:
        raise ValueError(f"The paper experiments require 5 RSUs; found {len(rsus)}")
    local_provider_count = ServiceProvider.objects.filter(
        type="vehicle",
        vehicle_id_id__in=[vehicle.id for vehicle in vehicles],
    ).values("vehicle_id_id").distinct().count()
    if local_provider_count != len(vehicles):
        raise ValueError("Every paper vehicle must have one local service provider")
    rsu_provider_count = ServiceProvider.objects.filter(
        type="rsu",
        rsu_id_id__in=[rsu.id for rsu in rsus],
    ).values("rsu_id_id").distinct().count()
    if rsu_provider_count != len(rsus):
        raise ValueError("Every paper RSU must have one service provider")
    application_types = list(ApplicationType.objects.order_by("deadline", "id"))
    by_deadline: Dict[int, ApplicationType] = {}
    for application_type in application_types:
        deadline_ms = int(application_type.deadline)
        if deadline_ms in DEADLINES_MS and deadline_ms not in by_deadline:
            by_deadline[deadline_ms] = application_type
    missing = [deadline for deadline in DEADLINES_MS if deadline not in by_deadline]
    if missing:
        raise ValueError(f"Application types are missing paper deadlines: {missing}")
    _validate_paper_parameters()
    _validate_paper_data(vehicles, rsus, by_deadline)
    return vehicles, rsus, by_deadline


def _road_geometry(vehicles: Sequence[Vehicle]) -> Tuple[float, List[float]]:
    road_length = 1000.0
    lane_values: List[float] = []
    for vehicle in vehicles:
        snapshot = vehicle.initial_snapshot or {}
        if snapshot.get("road_length_m") is not None:
            road_length = float(snapshot["road_length_m"])
        lane_x = snapshot.get("lane_x_coord")
        if lane_x is not None:
            lane_values.append(float(lane_x))
    lanes = sorted(set(lane_values))
    if not _close(road_length, 1000.0):
        raise ValueError(
            f"Road length is {road_length} m; Table III requires 1000 m"
        )
    if len(lanes) != 4:
        raise ValueError(
            f"The paper experiment requires 4 lanes; found {len(lanes)}"
        )
    lane_gaps = [lanes[index + 1] - lanes[index] for index in range(3)]
    if any(not _close(gap, 4.0) for gap in lane_gaps):
        raise ValueError(
            f"Lane coordinates do not represent the Table III width of 4 m: {lanes}"
        )
    return road_length, lanes


def _nearest_rsu_id(
    position: Tuple[float, float],
    rsus: Sequence[RSU],
    cell_radius_m: float,
    h_vehicle: float,
    h_rsu: float,
) -> int:
    nearest_id = None
    nearest_distance = None
    for rsu in rsus:
        distance = float(
            transmission.distance_3d(
                float(position[0]),
                float(position[1]),
                float(h_vehicle),
                float(rsu.x_coord),
                float(rsu.y_coord),
                float(h_rsu),
            )
        )
        if distance > float(cell_radius_m):
            continue
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_id = int(rsu.id)
    if nearest_id is None:
        raise ValueError(f"Vehicle position {position} is outside all RSU cells")
    return nearest_id


def _vehicle_count_for_speed(speed_kmh: float, road_length_m: float) -> int:
    spacing_m = 2.5 * (float(speed_kmh) / 3.6)
    expected = (4.0 * float(road_length_m)) / spacing_m
    return max(1, min(76, int(round(expected))))


def _road_state(
    vehicles: Sequence[Vehicle],
    rsus: Sequence[RSU],
    seed: int,
    road_vehicle_count: int,
    speed_kmh: float | None,
) -> Tuple[BenchmarkSnapshot, List[int], Dict[int, float], Dict[str, Any]]:
    if road_vehicle_count < 1 or road_vehicle_count > len(vehicles):
        raise ValueError("Invalid road vehicle count")
    params = load_params_obj()
    road_length_m, lane_x_values = _road_geometry(vehicles)
    rng = random.Random(int(seed) * 1000003 + 7919)
    ordered = list(vehicles)
    rng.shuffle(ordered)
    selected = ordered[:road_vehicle_count]
    positions: Dict[int, Tuple[float, float]] = {}
    speeds: Dict[int, float] = {}
    base_count, remainder = divmod(road_vehicle_count, len(lane_x_values))
    lane_counts = [
        base_count + (1 if index < remainder else 0)
        for index in range(len(lane_x_values))
    ]
    selected_index = 0
    for lane_x, lane_count in zip(lane_x_values, lane_counts):
        lane_positions = sorted(
            rng.uniform(0.0, road_length_m)
            for _ in range(lane_count)
        )
        for y_coord in lane_positions:
            vehicle = selected[selected_index]
            selected_index += 1
            positions[int(vehicle.id)] = (float(lane_x), float(y_coord))
            speeds[int(vehicle.id)] = (
                float(speed_kmh)
                if speed_kmh is not None
                else float(rng.uniform(60.0, 80.0))
            )
    vehicle_rsu_ids = {
        vehicle_id: _nearest_rsu_id(
            position,
            rsus,
            float(params.cell_radius_rsu),
            float(params.h_vehicle),
            float(params.h_rsu),
        )
        for vehicle_id, position in positions.items()
    }
    rsu_vehicle_counts: Dict[int, int] = {}
    for rsu_id in vehicle_rsu_ids.values():
        rsu_vehicle_counts[rsu_id] = rsu_vehicle_counts.get(rsu_id, 0) + 1
    snapshot = BenchmarkSnapshot(
        at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        time_step_s=0.0,
        positions=positions,
        vehicle_rsu_ids=vehicle_rsu_ids,
        rsu_vehicle_counts=rsu_vehicle_counts,
    )
    speed_values = list(speeds.values())
    metadata = {
        "road_vehicle_count": int(road_vehicle_count),
        "road_length_m": float(road_length_m),
        "number_of_lanes": 4,
        "mean_vehicle_speed_kmh": float(mean(speed_values)),
        "vehicle_speed_min_kmh": float(min(speed_values)),
        "vehicle_speed_max_kmh": float(max(speed_values)),
        "spatial_process": "spatial_poisson_conditioned_on_lane_vehicle_counts",
        "lane_vehicle_counts": lane_counts,
    }
    return snapshot, [int(vehicle.id) for vehicle in selected], speeds, metadata


def _assignments(
    road_vehicle_ids: Sequence[int],
    mission_vehicle_count: int,
    app_types: Dict[int, ApplicationType],
    seed: int,
    *,
    assignment_pool_count: int | None = None,
) -> List[Dict[str, int]]:
    """Build deterministic mission assignments for one seeded scenario.

    ``assignment_pool_count`` is used by Figure 7 to create one master
    76-vehicle assignment and then take prefixes of length 52, 56, ..., 76.
    Consequently, increasing the mission-vehicle count adds new applications
    without changing the vehicles or deadlines already present at smaller
    sweep points. Other figures keep their previous behavior by leaving this
    argument as ``None``.
    """
    if mission_vehicle_count > len(road_vehicle_ids):
        raise ValueError("Mission vehicle count exceeds road vehicle count")

    pool_count = (
        int(mission_vehicle_count)
        if assignment_pool_count is None
        else int(assignment_pool_count)
    )
    if pool_count < mission_vehicle_count:
        raise ValueError(
            "assignment_pool_count cannot be smaller than mission_vehicle_count"
        )
    if pool_count > len(road_vehicle_ids):
        raise ValueError("assignment_pool_count exceeds road vehicle count")

    rng = random.Random(int(seed) * 1000033 + 104729)

    # One stable mission order per seed. Figure 7 reuses the same full order
    # for every sweep point and only changes the prefix length.
    mission_order = list(road_vehicle_ids)
    rng.shuffle(mission_order)
    mission_order = mission_order[:pool_count]

    # Deadlines are assigned once over the full pool. This fixes the old
    # behavior where the same vehicle could receive a different deadline when
    # the sweep changed from, for example, 52 to 56 mission vehicles.
    deadline_sequence = [
        DEADLINES_MS[index % len(DEADLINES_MS)]
        for index in range(pool_count)
    ]
    rng.shuffle(deadline_sequence)

    rows: List[Dict[str, int]] = []
    for index in range(mission_vehicle_count):
        vehicle_id = mission_order[index]
        deadline_ms = deadline_sequence[index]
        rows.append(
            {
                "application_id": -(index + 1),
                "vehicle_id": int(vehicle_id),
                "application_type_id": int(app_types[deadline_ms].id),
            }
        )
    return rows


def _build_scenario(
    figure: str,
    seed: int,
    mission_vehicle_count: int,
    road_vehicle_count: int,
    speed_kmh: float | None,
    mec_capacity_ghz: float,
    sweep_parameter: str,
    sweep_value: float,
    environment: Tuple[
        List[Vehicle],
        List[RSU],
        Dict[int, ApplicationType],
    ],
    *,
    assignment_pool_count: int | None = None,
) -> Dict[str, Any]:
    vehicles, rsus, app_types = environment
    snapshot, road_vehicle_ids, speeds, road_metadata = _road_state(
        vehicles,
        rsus,
        seed,
        road_vehicle_count,
        speed_kmh,
    )
    assignments = _assignments(
        road_vehicle_ids,
        mission_vehicle_count,
        app_types,
        seed,
        assignment_pool_count=assignment_pool_count,
    )
    metadata = {
        "experiment_name": figure,
        "scenario_id": f"{figure}_seed_{seed}_{sweep_parameter}_{sweep_value}",
        "scenario_seed": int(seed),
        "sweep_parameter": sweep_parameter,
        "sweep_value": float(sweep_value),
        "mission_vehicle_count": int(mission_vehicle_count),
        "assignment_pool_count": int(
            assignment_pool_count
            if assignment_pool_count is not None
            else mission_vehicle_count
        ),
        "nested_mission_prefix": bool(assignment_pool_count is not None),
        "mean_mec_capacity_ghz": float(mec_capacity_ghz),
        "deadlines_s": [float(value) / 1000.0 for value in DEADLINES_MS],
        "article_speed_density_model": figure == "figure_9",
    }
    metadata.update(road_metadata)
    if speed_kmh is not None:
        metadata["average_intervehicle_distance_m"] = float(
            2.5 * (float(speed_kmh) / 3.6)
        )
    metadata["vehicle_speeds_kmh"] = {
        str(vehicle_id): float(value)
        for vehicle_id, value in speeds.items()
    }
    return build_synthetic_joint_context(
        assignments,
        snapshot,
        mec_capacity_ghz=mec_capacity_ghz,
        scenario_metadata=metadata,
    )


def _run_scenario(
    joint_ctx: Dict[str, Any],
    algorithms: Iterable[str],
    seed: int,
    tmax: int,
    population_size: int | None,
) -> Dict[str, Any]:
    return run_joint_context_benchmark(
        joint_ctx,
        algorithms=algorithms,
        seeds=[seed],
        tmax=tmax,
        population_size=population_size,
        export_artifacts=False,
    )


def _standard_rows(
    figure: str,
    result: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    scenario = result["scenario"]
    run_rows: List[Dict[str, Any]] = []
    application_rows: List[Dict[str, Any]] = []
    for run in result["runs"]:
        row = {
            "figure": figure,
            "scenario_id": scenario["scenario_id"],
            "seed": int(run["seed"]),
            "sweep_parameter": scenario["sweep_parameter"],
            "sweep_value": float(scenario["sweep_value"]),
            "mission_vehicle_count": int(scenario["mission_vehicle_count"]),
            "road_vehicle_count": int(scenario["road_vehicle_count"]),
            "mean_vehicle_speed_kmh": float(scenario["mean_vehicle_speed_kmh"]),
            "mean_mec_capacity_ghz": float(scenario["mean_mec_capacity_ghz"]),
            "algorithm": run["algorithm"],
            "avg_delay": float(run["metrics"]["avg_delay"]),
            "avg_efficiency": float(run["metrics"]["avg_efficiency"]),
            "total_efficiency": float(run["metrics"]["total_efficiency"]),
            "completion_rate": float(run["metrics"]["completion_rate"]),
        }
        run_rows.append(row)
        for application in run["applications"]:
            application_rows.append(
                {
                    **{key: row[key] for key in (
                        "figure",
                        "scenario_id",
                        "seed",
                        "sweep_parameter",
                        "sweep_value",
                        "algorithm",
                    )},
                    "application_id": int(application["application_id"]),
                    "vehicle_id": int(application["vehicle_id"]),
                    "deadline_s": float(application["deadline_s"]),
                    "alpha_n": float(application["alpha_n"]),
                    "beta_n": float(application["beta_n"]),
                    "delay_s": float(application["delay_s"]),
                    "energy_j": float(application["energy_j"]),
                    "efficiency": float(application["efficiency"]),
                    "completed": bool(application["completed"]),
                    "task_count": int(application["task_count"]),
                    "optimized_task_count": int(application["optimized_task_count"]),
                    "scheduled_task_count": int(application["scheduled_task_count"]),
                    "entry_task_id": int(application["entry_task_id"]),
                    "entry_provider_id": int(application["entry_provider_id"]),
                    "providers_used": json.dumps(
                        application.get("providers_used", []),
                        ensure_ascii=False,
                    ),
                }
            )
    return run_rows, application_rows


def _figure_8_rows(
    result: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    run_rows, application_rows = _standard_rows("figure_8", result)
    grouped: Dict[Tuple[str, int, float], List[Dict[str, Any]]] = {}
    for row in application_rows:
        key = (
            str(row["algorithm"]),
            int(row["seed"]),
            float(row["deadline_s"]),
        )
        grouped.setdefault(key, []).append(row)
    deadline_rows: List[Dict[str, Any]] = []
    for (algorithm, seed, deadline_s), rows in sorted(grouped.items()):
        deadline_rows.append(
            {
                "figure": "figure_8",
                "seed": seed,
                "algorithm": algorithm,
                "deadline_s": deadline_s,
                "deadline_ms": deadline_s * 1000.0,
                "avg_delay": float(mean(row["delay_s"] for row in rows)),
                "completion_rate": float(
                    mean(1.0 if row["completed"] else 0.0 for row in rows)
                ),
                "application_count": len(rows),
            }
        )
    return deadline_rows, application_rows


def _summary_rows(
    rows: Sequence[Dict[str, Any]],
    keys: Sequence[str],
    metrics: Sequence[str],
) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        grouped.setdefault(key, []).append(row)
    result: List[Dict[str, Any]] = []
    for key, selected in sorted(grouped.items(), key=lambda item: item[0]):
        summary = {name: value for name, value in zip(keys, key)}
        for metric in metrics:
            stats = _stats([float(row[metric]) for row in selected])
            summary[metric] = stats["mean"]
            summary[f"{metric}_std"] = stats["std"]
            summary[f"{metric}_min"] = stats["min"]
            summary[f"{metric}_max"] = stats["max"]
        summary["sample_count"] = len(selected)
        result.append(summary)
    return result


def _figure_6_summary_rows(
    rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return _summary_rows(
        rows,
        ("figure", "algorithm", "iteration", "point_type"),
        ("total_efficiency",),
    )


def _execution_audit_rows(
    figure: str,
    result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    scenario = result["scenario"]
    rows: List[Dict[str, Any]] = []
    for run in result["runs"]:
        applications = list(run.get("applications", []))
        schedule = list(run.get("schedule", []))
        mode_counts = {"local": 0, "v2v": 0, "v2i": 0}
        transfer_count = 0
        cache_update_count = 0
        for task in schedule:
            mode = str(task.get("provider_mode", ""))
            if mode in mode_counts:
                mode_counts[mode] += 1
            transfer_count += len(task.get("transfers", []))
            if bool(task.get("cache_update_required", False)):
                cache_update_count += 1
        rows.append(
            {
                "figure": figure,
                "scenario_id": scenario["scenario_id"],
                "seed": int(run["seed"]),
                "algorithm": str(run["algorithm"]),
                "application_count": len(applications),
                "completed_application_count": sum(
                    1 for application in applications if application["completed"]
                ),
                "total_energy_j": float(
                    sum(float(application["energy_j"]) for application in applications)
                ),
                "avg_delay_s": float(run["metrics"]["avg_delay"]),
                "avg_efficiency": float(run["metrics"]["avg_efficiency"]),
                "total_efficiency": float(run["metrics"]["total_efficiency"]),
                "completion_rate": float(run["metrics"]["completion_rate"]),
                "scheduled_task_count": len(schedule),
                "local_task_count": mode_counts["local"],
                "v2v_task_count": mode_counts["v2v"],
                "v2i_task_count": mode_counts["v2i"],
                "transfer_count": transfer_count,
                "cache_update_count": cache_update_count,
            }
        )
    return rows


def _iteration_diagnostics(item: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "accepted_candidates",
        "accepted_guided_trials",
        "accepted_cache_trials",
        "generated_trials",
        "unique_trial_count",
        "duplicate_trial_count",
        "mean_trial_hamming",
        "population_unique_count",
        "population_mean_hamming",
        "best_improved",
        "stagnation_generations",
        "initial_greedy_target",
        "initial_genetic_target",
        "initial_random_target",
        "initial_greedy_selected",
        "initial_genetic_selected",
        "initial_random_selected",
        "ga_generations",
        "genetic_candidate_pool_size",
        "random_candidate_pool_size",
    )
    return {key: item.get(key) for key in keys}


def _figure_6_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for run in result["runs"]:
        for item in run.get("iteration_history", []):
            iteration = int(float(item["iteration"]))
            population = item.get("population_total_efficiencies", [])
            for index, value in enumerate(population):
                rows.append(
                    {
                        "figure": "figure_6",
                        "algorithm": str(run["algorithm"]),
                        "seed": int(run["seed"]),
                        "iteration": iteration,
                        "function_evaluations": int(
                            item.get("function_evaluations", 0)
                        ),
                        "point_type": "population",
                        "population_index": index,
                        "total_efficiency": float(value),
                        "runtime_seconds": run.get("runtime_seconds"),
                        **_iteration_diagnostics(item),
                    }
                )
            rows.append(
                {
                    "figure": "figure_6",
                    "algorithm": str(run["algorithm"]),
                    "seed": int(run["seed"]),
                    "iteration": iteration,
                    "function_evaluations": int(
                        item.get("function_evaluations", 0)
                    ),
                    "point_type": "best",
                    "population_index": None,
                    "total_efficiency": float(item["best_total_efficiency"]),
                    "runtime_seconds": run.get("runtime_seconds"),
                    **_iteration_diagnostics(item),
                }
            )
    return rows


def _convergence_diagnostics(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for row in rows:
        if row.get("point_type") != "best":
            continue
        key = (str(row["algorithm"]), int(row["seed"]))
        grouped.setdefault(key, []).append(row)

    diagnostics = []
    for (algorithm, seed), selected in sorted(grouped.items()):
        selected.sort(key=lambda row: int(row["iteration"]))
        initial = selected[0]
        final = selected[-1]
        accepted = sum(
            int(row.get("accepted_candidates") or 0)
            for row in selected[1:]
        )
        generated = sum(
            int(row.get("generated_trials") or 0)
            for row in selected[1:]
        )
        unique_trials = sum(
            int(row.get("unique_trial_count") or 0)
            for row in selected[1:]
        )
        initial_best = float(initial["total_efficiency"])
        final_best = float(final["total_efficiency"])
        absolute_gain = final_best - initial_best
        improved_iterations = sum(
            1
            for previous, current in zip(selected, selected[1:])
            if float(current["total_efficiency"])
            > float(previous["total_efficiency"])
        )
        diagnostics.append(
            {
                "algorithm": algorithm,
                "seed": seed,
                "initial_best": initial_best,
                "final_best": final_best,
                "absolute_gain": absolute_gain,
                "relative_gain_percent": (
                    100.0 * absolute_gain / abs(initial_best)
                    if initial_best != 0.0
                    else None
                ),
                "improved_iterations": improved_iterations,
                "accepted_candidates": (
                    accepted if generated else None
                ),
                "generated_trials": generated if generated else None,
                "unique_trial_count": unique_trials if generated else None,
                "acceptance_rate": (
                    float(accepted / generated) if generated else None
                ),
                "function_evaluations": int(
                    final.get("function_evaluations", 0)
                ),
                "runtime_seconds": final.get("runtime_seconds"),
                "final_population_unique_count": final.get(
                    "population_unique_count"
                ),
                "final_population_mean_hamming": final.get(
                    "population_mean_hamming"
                ),
                "initial_greedy_selected": initial.get(
                    "initial_greedy_selected"
                ),
                "initial_genetic_selected": initial.get(
                    "initial_genetic_selected"
                ),
                "initial_random_selected": initial.get(
                    "initial_random_selected"
                ),
                "ga_generations": initial.get("ga_generations"),
                "genetic_candidate_pool_size": initial.get(
                    "genetic_candidate_pool_size"
                ),
                "random_candidate_pool_size": initial.get(
                    "random_candidate_pool_size"
                ),
                "stagnated": absolute_gain <= 0.0,
            }
        )
    return diagnostics


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _relative_path(path: Path) -> str:
    root = Path(settings.BASE_DIR).resolve()
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _algorithms_from_rows(rows: Sequence[Dict[str, Any]]) -> List[str]:
    algorithms: List[str] = []
    for row in rows:
        algorithm = str(row.get("algorithm", "")).strip()
        if algorithm and algorithm not in algorithms:
            algorithms.append(algorithm)
    return algorithms


def _plot_figure_6(rows: Sequence[Dict[str, Any]],output_base: Path,) -> None:
    """Plot all population members as points using the paper's axis scale."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    algorithms = _algorithms_from_rows(rows)
    if not algorithms:
        raise ValueError("Figure 6 has no algorithm data")

    population_rows = [
        row
        for row in rows
        if str(row.get("point_type", "")).strip().lower() == "population"
    ]
    if not population_rows:
        raise ValueError("Figure 6 has no population data")

    styles = {
        "dcsga": {"color": "#0072B2", "marker": "o"},
    }

    figure, axis = plt.subplots(figsize=(8.0, 5.2))
    paper_mode = algorithms == ["dcsga"]

    if paper_mode:
        selected_rows = [
            row
            for row in population_rows
            if str(row["algorithm"]) == "dcsga"
        ]
        selected_rows.sort(
            key=lambda row: (
                int(row["iteration"]),
                int(row["seed"]),
                int(row.get("population_index") or 0),
            )
        )
        axis.scatter(
            [int(row["iteration"]) for row in selected_rows],
            [float(row["total_efficiency"]) for row in selected_rows],
            s=13,
            color="black",
            alpha=0.80,
            marker="o",
            linewidths=0,
        )
    else:
        algorithm_count = len(algorithms)
        offset_step = 0.14
        center = (algorithm_count - 1) / 2.0

        for algorithm_index, algorithm in enumerate(algorithms):
            selected_rows = [
                row
                for row in population_rows
                if str(row["algorithm"]) == algorithm
            ]
            if not selected_rows:
                continue

            selected_rows.sort(
                key=lambda row: (
                    int(row["iteration"]),
                    int(row["seed"]),
                    int(row.get("population_index") or 0),
                )
            )

            style = styles.get(
                algorithm,
                {"color": None, "marker": "o"},
            )
            x_offset = (algorithm_index - center) * offset_step

            axis.scatter(
                [
                    float(row["iteration"]) + x_offset
                    for row in selected_rows
                ],
                [
                    float(row["total_efficiency"])
                    for row in selected_rows
                ],
                s=16,
                color=style["color"],
                marker=style["marker"],
                alpha=0.72,
                linewidths=0,
                label=ALGORITHM_LABELS.get(algorithm, algorithm),
            )

    iterations = sorted({
        int(row["iteration"])
        for row in population_rows
    })
    max_iteration = max(iterations)
    article_x_max = max(
        5,
        ((max_iteration + 4) // 5) * 5,
    )

    # Article-style axes:
    # x: 5 iterations per major tick
    # y: 18 to 25 with unit spacing
    axis.set_xlim(-0.5, article_x_max + 0.5)
    axis.set_xticks(list(range(0, article_x_max + 1, 5)))
    axis.set_ylim(18.0, 29.0)
    axis.set_yticks([
        18.0, 19.0, 20.0, 21.0,
        22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0,
    ])

    axis.set_xlabel("Number of iterations")
    axis.set_ylabel("Total offloading efficiency")
    axis.grid(alpha=0.25, linestyle=":")

    if not paper_mode:
        axis.legend(frameon=False)

    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)

def _line_panel(axis, rows: Sequence[Dict[str, Any]], metric: str, x_key: str, x_label: str, y_label: str,
) -> None:
    """Draw one Figure 7/8 panel from aggregated summary rows.

    Standard deviations remain available in CSV/JSON outputs, but uncertainty
    bands are intentionally not drawn so the exported figures match the
    article layout and completion-rate plots never extend below zero.
    """
    algorithms = _algorithms_from_rows(rows)
    if not algorithms:
        raise ValueError("The plot has no algorithm data")

    styles = {
        "dcsga": {
            "color": "#0072B2",
            "marker": "o",
            "linestyle": "-",
        },
        "dtosc": {
            "color": "#009E73",
            "marker": "^",
            "linestyle": "-.",
        },
        "to_v2i": {
            "color": "#CC79A7",
            "marker": "D",
            "linestyle": ":",
        },
        "to_wo_c": {
            "color": "#56B4E9",
            "marker": "v",
            "linestyle": (0, (5, 2)),
        },
        "to_wo_r": {
            "color": "#E69F00",
            "marker": "P",
            "linestyle": (0, (1, 1)),
        },
    }

    all_x_values = set()

    for algorithm in algorithms:
        algorithm_rows = sorted(
            (
                row
                for row in rows
                if row.get("algorithm") == algorithm
                and row.get(x_key) is not None
                and row.get(metric) is not None
            ),
            key=lambda row: float(row[x_key]),
        )
        if not algorithm_rows:
            continue

        style = styles.get(
            algorithm,
            {
                "color": None,
                "marker": "o",
                "linestyle": "-",
            },
        )
        x_values = [float(row[x_key]) for row in algorithm_rows]
        y_values = [float(row[metric]) for row in algorithm_rows]
        all_x_values.update(x_values)

        axis.plot(
            x_values,
            y_values,
            color=style["color"],
            marker=style["marker"],
            linestyle=style["linestyle"],
            linewidth=2.2,
            markersize=5.5,
            label=ALGORITHM_LABELS.get(algorithm, algorithm),
        )

    if not all_x_values:
        raise ValueError(f"The plot has no valid values for {metric}")

    axis.set_xticks(sorted(all_x_values))
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.grid(alpha=0.25, linestyle=":")
    axis.legend(frameon=False)

def _plot_figure_7(rows: Sequence[Dict[str, Any]], output_base: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(2, 2, figsize=(10, 8))
    specs = (
        (
            "avg_delay",
            "Average delay (s)",
            (0.02, 0.07),
            [0.02, 0.03, 0.04, 0.05, 0.06, 0.07],
        ),
        (
            "avg_efficiency",
            "Average offloading efficiency",
            (0.0, 0.6),
            [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        ),
        (
            "total_efficiency",
            "Total offloading efficiency",
            (0.0, 40.0),
            [0.0, 10.0, 20.0, 30.0, 40.0],
        ),
        (
            "completion_rate",
            "Rate of completion",
            (0.6, 1.0),
            [0.6, 0.7, 0.8, 0.9, 1.0],
        ),
    )
    for axis, (metric, y_label, y_limits, y_ticks) in zip(axes.flat, specs):
        _line_panel(
            axis,
            list(rows),
            metric,
            "mission_vehicle_count",
            "Number of vehicles",
            y_label,
        )
        axis.set_ylim(*y_limits)
        axis.set_yticks(y_ticks)

    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)



def _plot_figure_8(rows: Sequence[Dict[str, Any]],output_base: Path,) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(10, 4))

    _line_panel(
        axes[0],
        list(rows),
        "avg_delay",
        "deadline_s",
        "Deadline of application (s)",
        "Average delay (s)",
    )
    _line_panel(
        axes[1],
        list(rows),
        "completion_rate",
        "deadline_s",
        "Deadline of application (s)",
        "Rate of completion",
    )

    deadline_ticks = [
        0.03, 0.04, 0.05, 0.06,
        0.07, 0.08, 0.09, 0.10,
    ]
    for axis in axes:
        axis.set_xticks(deadline_ticks)

    # Figure 8(a): 0.02 to 0.08, one-hundredth spacing.
    axes[0].set_ylim(0.02, 0.08)
    axes[0].set_yticks([
        0.02, 0.03, 0.04, 0.05,
        0.06, 0.07, 0.08,
    ])

    # Figure 8(b): 0 to 1, 0.2 spacing.
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_yticks([
        0.0, 0.2, 0.4, 0.6, 0.8, 1.0,
    ])

    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)

def _plot_figure_9(rows: Sequence[Dict[str, Any]],output_base: Path,) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    speeds = list(VEHICLE_SPEEDS_KMH)
    algorithms = _algorithms_from_rows(rows)
    width = 0.8 / max(1, len(algorithms))
    x_values = list(range(len(speeds)))

    figure, axis = plt.subplots()

    for algorithm_index, algorithm in enumerate(algorithms):
        values_by_speed = {
            int(round(float(row["speed_kmh"]))): float(
                row["total_efficiency"]
            )
            for row in rows
            if row["algorithm"] == algorithm
        }
        offset = (
            algorithm_index - (len(algorithms) - 1) / 2.0
        ) * width

        axis.bar(
            [value + offset for value in x_values],
            [
                values_by_speed.get(speed, 0.0)
                for speed in speeds
            ],
            width=width,
            label=ALGORITHM_LABELS.get(algorithm, algorithm),
        )

    # Article-style axes:
    # x: 75 to 105 km/h, 5 km/h spacing
    # y: 20 to 25, unit spacing
    axis.set_xticks(
        x_values,
        [str(speed) for speed in speeds],
    )
    axis.set_ylim(20.0, 25.0)
    axis.set_yticks([
        20.0, 21.0, 22.0,
        23.0, 24.0, 25.0,
    ])

    axis.set_xlabel("Speed of vehicles (km/h)")
    axis.set_ylabel("Total offloading efficiency")
    axis.grid(axis="y", alpha=0.3)
    axis.legend()

    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)

def _plot_figure_10(
    rows: Sequence[Dict[str, Any]],
    output_base: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, efficiency_axis = plt.subplots(figsize=(8.0, 5.2))
    completion_axis = efficiency_axis.twinx()

    styles = {
        "dcsga": {"color": "#0072B2", "marker": "o"},
        "dtosc": {"color": "#009E73", "marker": "^"},
    }

    for algorithm in _algorithms_from_rows(rows):
        selected = sorted(
            (
                row
                for row in rows
                if row["algorithm"] == algorithm
            ),
            key=lambda row: float(row["mec_capacity_ghz"]),
        )
        if not selected:
            continue

        style = styles.get(
            algorithm,
            {"color": None, "marker": "o"},
        )
        x_values = [
            float(row["mec_capacity_ghz"])
            for row in selected
        ]
        label = ALGORITHM_LABELS.get(algorithm, algorithm)

        efficiency_axis.plot(
            x_values,
            [
                float(row["avg_efficiency"])
                for row in selected
            ],
            color=style["color"],
            marker=style["marker"],
            linestyle="-",
            linewidth=2.2,
            markersize=5.5,
            label=f"{label} efficiency",
        )
        completion_axis.plot(
            x_values,
            [
                float(row["completion_rate"])
                for row in selected
            ],
            color=style["color"],
            marker=style["marker"],
            linestyle="--",
            linewidth=1.8,
            markersize=5.0,
            label=f"{label} completion",
        )

    efficiency_axis.set_xlim(28.0, 82.0)
    efficiency_axis.set_xticks([30, 40, 50, 60, 70, 80])

    efficiency_axis.set_ylim(0.20, 0.50)
    efficiency_axis.set_yticks([
        0.20, 0.25, 0.30, 0.35,
        0.40, 0.45, 0.50,
    ])

    completion_axis.set_ylim(0.988, 1.000)
    completion_axis.set_yticks([
        0.988, 0.990, 0.992, 0.994,
        0.996, 0.998, 1.000,
    ])

    efficiency_axis.set_xlabel(
        "Computing capacity of MEC servers (GHz)"
    )
    efficiency_axis.set_ylabel(
        "Average offloading efficiency"
    )
    completion_axis.set_ylabel(
        "Rate of completion"
    )
    efficiency_axis.grid(alpha=0.3, linestyle=":")

    handles_a, labels_a = (
        efficiency_axis.get_legend_handles_labels()
    )
    handles_b, labels_b = (
        completion_axis.get_legend_handles_labels()
    )
    figure.legend(
        handles_a + handles_b,
        labels_a + labels_b,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=3,
        frameon=False,
    )

    figure.tight_layout(rect=(0.0, 0.12, 1.0, 1.0))
    figure.savefig(
        output_base.with_suffix(".png"),
        dpi=300,
        bbox_inches="tight",
    )
    figure.savefig(
        output_base.with_suffix(".pdf"),
        bbox_inches="tight",
    )
    plt.close(figure)
def _export_experiment(
    figure: str,
    raw_rows: Sequence[Dict[str, Any]],
    summary_rows: Sequence[Dict[str, Any]],
    application_rows: Sequence[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    run_id = (
        f"{figure}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{uuid4().hex[:8]}"
    )
    experiment_folder = (
        "algorithm_comparison"
        if metadata.get("comparison_mode", False)
        else "paper_figures"
    )
    output_dir = (
        Path(settings.BASE_DIR)
        / "benchmark_results"
        / experiment_folder
        / figure
        / run_id
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    raw_path = output_dir / "raw_results.csv"
    summary_path = output_dir / "summary_results.csv"
    application_path = output_dir / "application_results.csv"
    metadata_path = output_dir / "metadata.json"
    _write_csv(raw_path, raw_rows)
    _write_csv(summary_path, summary_rows)
    _write_csv(application_path, application_rows)
    with metadata_path.open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2, default=str)
    figure_base = output_dir / figure
    if figure == "figure_6":
        _plot_figure_6(raw_rows, figure_base)
    elif figure == "figure_7":
        _plot_figure_7(summary_rows, figure_base)
    elif figure == "figure_8":
        _plot_figure_8(summary_rows, figure_base)
    elif figure == "figure_9":
        _plot_figure_9(summary_rows, figure_base)
    elif figure == "figure_10":
        _plot_figure_10(summary_rows, figure_base)
    return {
        "run_id": run_id,
        "output_directory": _relative_path(output_dir),
        "raw_csv": _relative_path(raw_path),
        "summary_csv": _relative_path(summary_path),
        "application_csv": _relative_path(application_path),
        "metadata_json": _relative_path(metadata_path),
        "figure_png": _relative_path(figure_base.with_suffix(".png")),
        "figure_pdf": _relative_path(figure_base.with_suffix(".pdf")),
    }


def run_paper_experiment(
    figure: str,
    repetitions: int | None = None,
    seed_start: int = 1,
    tmax: int = 15,
    population_size: int | None = None,
    algorithms: Iterable[str] | None = None,
    diagnostic_vehicle_count: int | None = None,
    export_artifacts: bool = True,
) -> Dict[str, Any]:
    figure = _normalize_figure(figure)
    if figure == "all":
        figures = list(FIGURE_ALGORITHMS)
        return {
            "figure": "all",
            "requested_figures": figures,
            "seed_start": int(seed_start),
            "tmax": int(tmax),
            "population_size": (
                None if population_size is None else int(population_size)
            ),
            "results": {
                item: run_paper_experiment(
                    figure=item,
                    repetitions=repetitions,
                    seed_start=seed_start,
                    tmax=tmax,
                    population_size=population_size,
                    algorithms=algorithms,
                    diagnostic_vehicle_count=None,
                    export_artifacts=export_artifacts,
                )
                for item in figures
            },
        }
    if repetitions is None:
        repetitions = 100 if figure == "figure_8" else 1
    repetitions = int(repetitions)
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    tmax = int(tmax)
    if tmax < 1:
        raise ValueError("tmax must be positive")
    if population_size is not None and int(population_size) < 2:
        raise ValueError("population_size must be at least 2")
    if diagnostic_vehicle_count is not None:
        diagnostic_vehicle_count = int(diagnostic_vehicle_count)
        if figure != "figure_6":
            raise ValueError(
                "diagnostic_vehicle_count is supported only for figure_6"
            )
        if diagnostic_vehicle_count < 2 or diagnostic_vehicle_count > 76:
            raise ValueError(
                "diagnostic_vehicle_count must be between 2 and 76"
            )
    seeds = [int(seed_start) + index for index in range(repetitions)]
    default_algorithms = FIGURE_ALGORITHMS[figure]
    paper_algorithms = PAPER_FIGURE_ALGORITHMS[figure]
    if algorithms is None:
        selected_algorithms = tuple(default_algorithms)
    else:
        selected_algorithms = tuple(
            dict.fromkeys(str(name).strip().lower() for name in algorithms)
        )
    if not selected_algorithms:
        raise ValueError("At least one algorithm is required")
    unknown_algorithms = [
        name for name in selected_algorithms if name not in ALGORITHM_LABELS
    ]
    if unknown_algorithms:
        raise ValueError(f"Unsupported comparison algorithms: {unknown_algorithms}")
    if figure == "figure_6" and "dtosc" in selected_algorithms:
        raise ValueError("DTOSC has no population convergence history for Figure 6")
    algorithms = selected_algorithms
    comparison_mode = tuple(algorithms) != tuple(paper_algorithms)
    environment = _load_paper_environment()
    raw_rows: List[Dict[str, Any]] = []
    application_rows: List[Dict[str, Any]] = []
    execution_audit: List[Dict[str, Any]] = []
    scenario_records: List[Dict[str, Any]] = []

    if figure == "figure_6":
        figure_6_vehicle_count = int(diagnostic_vehicle_count or 76)
        for seed in seeds:
            joint_ctx = _build_scenario(
                figure,
                seed,
                mission_vehicle_count=figure_6_vehicle_count,
                road_vehicle_count=figure_6_vehicle_count,
                speed_kmh=None,
                mec_capacity_ghz=50.0,
                sweep_parameter="iteration",
                sweep_value=float(tmax - 1),
                environment=environment,
            )
            result = _run_scenario(
                joint_ctx,
                algorithms,
                seed,
                tmax,
                population_size,
            )
            raw_rows.extend(_figure_6_rows(result))
            _, apps = _standard_rows(figure, result)
            application_rows.extend(apps)
            execution_audit.extend(_execution_audit_rows(figure, result))
            scenario_records.append(dict(result["scenario"]))
        summary_rows = _figure_6_summary_rows(raw_rows)
    elif figure == "figure_7":
        for vehicle_count in VEHICLE_COUNTS:
            for seed in seeds:
                joint_ctx = _build_scenario(
                    figure,
                    seed,
                    mission_vehicle_count=vehicle_count,
                    road_vehicle_count=76,
                    speed_kmh=None,
                    mec_capacity_ghz=50.0,
                    sweep_parameter="mission_vehicle_count",
                    sweep_value=float(vehicle_count),
                    environment=environment,
                    assignment_pool_count=max(VEHICLE_COUNTS),
                )
                result = _run_scenario(
                    joint_ctx,
                    algorithms,
                    seed,
                    tmax,
                    population_size,
                )
                run_rows, apps = _standard_rows(figure, result)
                raw_rows.extend(run_rows)
                application_rows.extend(apps)
                execution_audit.extend(
                    _execution_audit_rows(figure, result)
                )
                scenario_records.append(dict(result["scenario"]))
        summary_rows = _summary_rows(
            raw_rows,
            ("figure", "mission_vehicle_count", "algorithm"),
            ("avg_delay", "avg_efficiency", "total_efficiency", "completion_rate"),
        )
    elif figure == "figure_8":
        for seed in seeds:
            joint_ctx = _build_scenario(
                figure,
                seed,
                mission_vehicle_count=68,
                road_vehicle_count=76,
                speed_kmh=None,
                mec_capacity_ghz=50.0,
                sweep_parameter="deadline_s",
                sweep_value=0.0,
                environment=environment,
            )
            result = _run_scenario(
                joint_ctx,
                algorithms,
                seed,
                tmax,
                population_size,
            )
            deadline_rows, apps = _figure_8_rows(result)
            raw_rows.extend(deadline_rows)
            application_rows.extend(apps)
            execution_audit.extend(
                _execution_audit_rows(figure, result)
            )
            scenario_records.append(dict(result["scenario"]))
        summary_rows = _summary_rows(
            raw_rows,
            ("figure", "deadline_s", "deadline_ms", "algorithm"),
            ("avg_delay", "completion_rate"),
        )
    elif figure == "figure_9":
        road_length_m, _ = _road_geometry(environment[0])
        for speed_kmh in VEHICLE_SPEEDS_KMH:
            vehicle_count = _vehicle_count_for_speed(speed_kmh, road_length_m)
            for seed in seeds:
                joint_ctx = _build_scenario(
                    figure,
                    seed,
                    mission_vehicle_count=vehicle_count,
                    road_vehicle_count=vehicle_count,
                    speed_kmh=float(speed_kmh),
                    mec_capacity_ghz=50.0,
                    sweep_parameter="speed_kmh",
                    sweep_value=float(speed_kmh),
                    environment=environment,
                )
                result = _run_scenario(
                    joint_ctx,
                    algorithms,
                    seed,
                    tmax,
                    population_size,
                )
                run_rows, apps = _standard_rows(figure, result)
                for row in run_rows:
                    row["speed_kmh"] = float(speed_kmh)
                raw_rows.extend(run_rows)
                application_rows.extend(apps)
                execution_audit.extend(
                    _execution_audit_rows(figure, result)
                )
                scenario_records.append(dict(result["scenario"]))
        summary_rows = _summary_rows(
            raw_rows,
            ("figure", "speed_kmh", "algorithm"),
            ("total_efficiency",),
        )
    else:
        for capacity_ghz in MEC_CAPACITIES_GHZ:
            for seed in seeds:
                joint_ctx = _build_scenario(
                    figure,
                    seed,
                    mission_vehicle_count=68,
                    road_vehicle_count=76,
                    speed_kmh=None,
                    mec_capacity_ghz=float(capacity_ghz),
                    sweep_parameter="mec_capacity_ghz",
                    sweep_value=float(capacity_ghz),
                    environment=environment,
                )
                result = _run_scenario(
                    joint_ctx,
                    algorithms,
                    seed,
                    tmax,
                    population_size,
                )
                run_rows, apps = _standard_rows(figure, result)
                for row in run_rows:
                    row["mec_capacity_ghz"] = float(capacity_ghz)
                raw_rows.extend(run_rows)
                application_rows.extend(apps)
                execution_audit.extend(
                    _execution_audit_rows(figure, result)
                )
                scenario_records.append(dict(result["scenario"]))
        summary_rows = _summary_rows(
            raw_rows,
            ("figure", "mec_capacity_ghz", "algorithm"),
            ("avg_efficiency", "completion_rate"),
        )

    metadata = {
        "figure": figure,
        "article_doi": ARTICLE_DOI,
        "repetitions": repetitions,
        "seeds": seeds,
        "tmax": int(tmax),
        "population_size": int(
            population_size if population_size is not None else load_params_obj().S
        ),
        "population_size_matches_paper": int(
            population_size if population_size is not None else load_params_obj().S
        ) == 50,
        "algorithms": list(algorithms),
        "comparison_mode": comparison_mode,
        "diagnostic_mode": bool(
            figure == "figure_6"
            and diagnostic_vehicle_count is not None
            and int(diagnostic_vehicle_count) != 76
        ),
        "diagnostic_vehicle_count": (
            None
            if diagnostic_vehicle_count is None
            else int(diagnostic_vehicle_count)
        ),
        "default_paper_algorithms": list(paper_algorithms),
        "default_run_algorithms": list(default_algorithms),
        "arrival_model": {
            "application_rate_per_second": float(
                load_params_obj().application_rate_per_second
            ),
            "dynamic_arrivals_applied": False,
            "figure_7_scheduling_epoch": (
                "one concurrent application per mission vehicle"
            ),
            "reason": (
                "The article reports 10 applications per second but does not "
                "specify the arrival distribution, observation horizon, or "
                "whether the rate is per vehicle or system-wide. Figure 7 is "
                "therefore evaluated as the joint scheduling epoch defined by "
                "Algorithm 2 instead of imposing an unverified arrival model."
            ),
        },
        "article_parameters": {
            "vehicle_counts": list(VEHICLE_COUNTS),
            "deadlines_ms": list(DEADLINES_MS),
            "vehicle_speeds_kmh": list(VEHICLE_SPEEDS_KMH),
            "mec_capacities_ghz": list(MEC_CAPACITIES_GHZ),
            "figure_8_repetitions": 100,
            "figure_8_vehicle_count": 68,
            "figure_10_vehicle_count": 68,
            "population_size": 50,
            "speed_density_rule": "mean inter-vehicle distance equals 2.5 times mean speed in m/s",
        },
        "declared_limitations": [
            "DTOSC uses a complete semi-distributed stage-wise dynamic-programming reconstruction aligned with the published description; source-exact line-by-line verification is not claimed because the 2022 pseudocode is not bundled with the project.",
            "The channel and sender-side power models remain declared approximations.",
            "Figures 6-10 evaluate one joint scheduling epoch. The article reports 10 applications per second but does not define a reproducible arrival distribution, observation horizon, or whether that rate is per vehicle or system-wide; no unverified arrival process is imposed on the paper figures.",
            "For Figures 7, 8, and 10, the road vehicle pool is fixed at the available 76 vehicles while the paper-specified mission vehicle count is varied or fixed; the paper does not report a separate total road vehicle count for these figures.",
            "Figure 9 uses a finite spatial-Poisson realization conditioned on the speed-derived lane vehicle counts because the database contains 76 vehicle records.",
            "The service compile workload Wk is not reported in Table III and is set equal to the corresponding task workload as a declared deterministic assumption.",
            "The available application types use the same seeded ten-task DAG structure with different deadlines, so the DAG diversity of reference [48] is not reproduced.",
        ],
        "scenario_records": scenario_records,
        "execution_audit": execution_audit,
    }
    convergence_diagnostics = (
        _convergence_diagnostics(raw_rows)
        if figure == "figure_6"
        else []
    )
    artifacts = {}
    if export_artifacts:
        artifacts = _export_experiment(
            figure,
            raw_rows,
            summary_rows,
            application_rows,
            metadata,
        )
    return {
        **metadata,
        "convergence_diagnostics": convergence_diagnostics,
        "summary": summary_rows,
        "artifacts": artifacts,
    }