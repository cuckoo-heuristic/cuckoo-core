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
FIGURE_ALGORITHMS = {
    "figure_6": ("dcsga",),
    "figure_7": ("dcsga", "dtosc", "to_v2i", "to_wo_c", "to_wo_r"),
    "figure_8": ("dcsga", "to_wo_c", "to_wo_r"),
    "figure_9": ("dcsga", "dtosc"),
    "figure_10": ("dcsga", "dtosc"),
}



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
) -> List[Dict[str, int]]:
    if mission_vehicle_count > len(road_vehicle_ids):
        raise ValueError("Mission vehicle count exceeds road vehicle count")
    rng = random.Random(int(seed) * 1000033 + 104729)
    mission_order = list(road_vehicle_ids)
    rng.shuffle(mission_order)
    mission_order = mission_order[:mission_vehicle_count]
    deadline_sequence = [
        DEADLINES_MS[index % len(DEADLINES_MS)]
        for index in range(mission_vehicle_count)
    ]
    rng.shuffle(deadline_sequence)
    rows: List[Dict[str, int]] = []
    for index, vehicle_id in enumerate(mission_order):
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
    )
    metadata = {
        "experiment_name": figure,
        "scenario_id": f"{figure}_seed_{seed}_{sweep_parameter}_{sweep_value}",
        "scenario_seed": int(seed),
        "sweep_parameter": sweep_parameter,
        "sweep_value": float(sweep_value),
        "mission_vehicle_count": int(mission_vehicle_count),
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
        ("figure", "iteration", "point_type"),
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


def _figure_6_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for run in result["runs"]:
        if run["algorithm"] != "dcsga":
            continue
        for item in run.get("iteration_history", []):
            iteration = int(float(item["iteration"]))
            population = item.get("population_total_efficiencies", [])
            for index, value in enumerate(population):
                rows.append(
                    {
                        "figure": "figure_6",
                        "seed": int(run["seed"]),
                        "iteration": iteration,
                        "point_type": "population",
                        "population_index": index,
                        "total_efficiency": float(value),
                    }
                )
            rows.append(
                {
                    "figure": "figure_6",
                    "seed": int(run["seed"]),
                    "iteration": iteration,
                    "point_type": "best",
                    "population_index": None,
                    "total_efficiency": float(item["best_total_efficiency"]),
                }
            )
    return rows


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


def _plot_figure_6(rows: Sequence[Dict[str, Any]], output_base: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    population = [row for row in rows if row["point_type"] == "population"]
    if not population:
        raise ValueError("Figure 6 has no population convergence points")
    figure, axis = plt.subplots()
    axis.scatter(
        [row["iteration"] for row in population],
        [row["total_efficiency"] for row in population],
        s=7,
    )
    iterations = sorted({int(row["iteration"]) for row in population})
    axis.set_xticks(iterations)
    axis.set_xlabel("Number of iterations")
    axis.set_ylabel("Total offloading efficiency")
    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)


def _line_panel(axis, rows, metric, x_key, x_label, y_label) -> None:
    algorithms = FIGURE_ALGORITHMS[rows[0]["figure"]]
    for algorithm in algorithms:
        selected = sorted(
            (row for row in rows if row["algorithm"] == algorithm),
            key=lambda row: float(row[x_key]),
        )
        axis.plot(
            [row[x_key] for row in selected],
            [row[metric] for row in selected],
            marker="o",
            label=ALGORITHM_LABELS[algorithm],
        )
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.grid(alpha=0.3)
    axis.legend()


def _plot_figure_7(rows: Sequence[Dict[str, Any]], output_base: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(2, 2, figsize=(10, 8))
    specs = (
        ("avg_delay", "Average delay (s)"),
        ("avg_efficiency", "Average offloading efficiency"),
        ("total_efficiency", "Total offloading efficiency"),
        ("completion_rate", "Rate of completion"),
    )
    for axis, (metric, y_label) in zip(axes.flat, specs):
        _line_panel(
            axis,
            list(rows),
            metric,
            "mission_vehicle_count",
            "Number of vehicles",
            y_label,
        )
    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)


def _plot_figure_8(rows: Sequence[Dict[str, Any]], output_base: Path) -> None:
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
    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)


def _plot_figure_9(rows: Sequence[Dict[str, Any]], output_base: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    speeds = list(VEHICLE_SPEEDS_KMH)
    algorithms = FIGURE_ALGORITHMS["figure_9"]
    width = 0.36
    x_values = list(range(len(speeds)))
    figure, axis = plt.subplots()
    for algorithm_index, algorithm in enumerate(algorithms):
        values_by_speed = {
            int(round(float(row["speed_kmh"]))): float(row["total_efficiency"])
            for row in rows
            if row["algorithm"] == algorithm
        }
        offset = (algorithm_index - 0.5) * width
        axis.bar(
            [value + offset for value in x_values],
            [values_by_speed[speed] for speed in speeds],
            width=width,
            label=ALGORITHM_LABELS[algorithm],
        )
    axis.set_xticks(x_values, [str(speed) for speed in speeds])
    axis.set_xlabel("Speed of vehicles (km/h)")
    axis.set_ylabel("Total offloading efficiency")
    axis.grid(axis="y", alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
    plt.close(figure)


def _plot_figure_10(rows: Sequence[Dict[str, Any]], output_base: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, efficiency_axis = plt.subplots()
    completion_axis = efficiency_axis.twinx()
    for algorithm in FIGURE_ALGORITHMS["figure_10"]:
        selected = sorted(
            (row for row in rows if row["algorithm"] == algorithm),
            key=lambda row: float(row["mec_capacity_ghz"]),
        )
        x_values = [row["mec_capacity_ghz"] for row in selected]
        efficiency_axis.plot(
            x_values,
            [row["avg_efficiency"] for row in selected],
            marker="o",
            linestyle="-",
            label=f"{ALGORITHM_LABELS[algorithm]} efficiency",
        )
        completion_axis.plot(
            x_values,
            [row["completion_rate"] for row in selected],
            marker="o",
            linestyle="--",
            label=f"{ALGORITHM_LABELS[algorithm]} completion",
        )
    efficiency_axis.set_xlabel("Computing capacity of MEC servers (GHz)")
    efficiency_axis.set_ylabel("Average offloading efficiency")
    completion_axis.set_ylabel("Rate of completion")
    efficiency_axis.grid(alpha=0.3)
    handles_a, labels_a = efficiency_axis.get_legend_handles_labels()
    handles_b, labels_b = completion_axis.get_legend_handles_labels()
    efficiency_axis.legend(handles_a + handles_b, labels_a + labels_b)
    figure.tight_layout()
    figure.savefig(output_base.with_suffix(".png"), dpi=300)
    figure.savefig(output_base.with_suffix(".pdf"))
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
    output_dir = (
        Path(settings.BASE_DIR)
        / "benchmark_results"
        / "paper_figures"
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
    seeds = [int(seed_start) + index for index in range(repetitions)]
    algorithms = FIGURE_ALGORITHMS[figure]
    environment = _load_paper_environment()
    raw_rows: List[Dict[str, Any]] = []
    application_rows: List[Dict[str, Any]] = []
    execution_audit: List[Dict[str, Any]] = []
    scenario_records: List[Dict[str, Any]] = []

    if figure == "figure_6":
        for seed in seeds:
            joint_ctx = _build_scenario(
                figure,
                seed,
                mission_vehicle_count=76,
                road_vehicle_count=76,
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
            "The isolated figures use simultaneous application snapshots and do not reproduce the runtime arrival process.",
            "For Figures 7, 8, and 10, the road vehicle pool is fixed at the available 76 vehicles while the paper-specified mission vehicle count is varied or fixed; the paper does not report a separate total road vehicle count for these figures.",
            "Figure 9 uses a finite spatial-Poisson realization conditioned on the speed-derived lane vehicle counts because the database contains 76 vehicle records.",
            "The service compile workload Wk is not reported in Table III and is set equal to the corresponding task workload as a declared deterministic assumption.",
            "The available application types use the same seeded ten-task DAG structure with different deadlines, so the DAG diversity of reference [48] is not reproduced.",
        ],
        "scenario_records": scenario_records,
        "execution_audit": execution_audit,
    }
    artifacts = _export_experiment(
        figure,
        raw_rows,
        summary_rows,
        application_rows,
        metadata,
    )
    return {
        **metadata,
        "summary": summary_rows,
        "artifacts": artifacts,
    }