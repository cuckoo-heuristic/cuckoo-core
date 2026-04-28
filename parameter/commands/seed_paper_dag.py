from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from task.models import ApplicationType, Task, TaskDependency, TaskType


def _load_snapshot(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise CommandError(f"Snapshot file not found: {path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise CommandError(f"Invalid JSON snapshot: {e}")


def _get_or_create_task_type(name: str, description: str | None = None) -> TaskType:
    obj = TaskType.objects.filter(name=name).first()
    if obj is not None:
        return obj
    return TaskType.objects.create(name=name, description=description)


def _validate_snapshot(s: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    tasks = s.get("tasks")
    edges = s.get("dependencies") or s.get("edges")
    if not isinstance(tasks, list) or not tasks:
        raise CommandError("Snapshot must contain non-empty list: tasks")
    if not isinstance(edges, list):
        edges = []
    return tasks, edges


class Command(BaseCommand):
    help = "Seed ApplicationType/TaskType/Task/TaskDependency from a paper DAG snapshot JSON."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="ApplicationType.name")
        parser.add_argument("--deadline-ms", required=True, type=int, help="ApplicationType.deadline (ms)")
        parser.add_argument("--description", default="seeded from snapshot", help="ApplicationType.description")
        parser.add_argument("--snapshot", required=True, help="Path to snapshot JSON file")
        parser.add_argument("--replace", action="store_true", help="Delete existing tasks/deps for this ApplicationType before inserting")

    @transaction.atomic
    def handle(self, *args, **opts):
        name: str = opts["name"]
        deadline_ms: int = int(opts["deadline_ms"])
        description: str = opts["description"]
        snapshot_path: str = opts["snapshot"]
        replace: bool = bool(opts["replace"])

        snap = _load_snapshot(snapshot_path)
        tasks_raw, edges_raw = _validate_snapshot(snap)

        app_type = ApplicationType.objects.filter(name=name).first()
        if app_type is None:
            app_type = ApplicationType.objects.create(
                name=name,
                deadline=deadline_ms,
                description=description,
                initial_snapshot=snap,
            )
        else:
            app_type.deadline = deadline_ms
            app_type.description = description
            app_type.initial_snapshot = snap
            app_type.save(update_fields=["deadline", "description", "initial_snapshot"])

        if replace:
            TaskDependency.objects.filter(
                parent_task_id__application_type_id=app_type
            ).delete()
            Task.objects.filter(application_type_id=app_type).delete()

        created_tasks: Dict[int, Task] = {}

        for t in tasks_raw:
            if not isinstance(t, dict):
                raise CommandError("Each task must be an object")
            index = t.get("index")
            if index is None:
                raise CommandError("Each task must have: index")
            idx = int(index)

            tt_name = t.get("task_type") or t.get("type") or f"T{idx}"
            tt_desc = t.get("task_type_desc") or t.get("description")

            task_type = _get_or_create_task_type(str(tt_name), str(tt_desc) if tt_desc is not None else None)

            workload_cycles = t.get("workload_cycles")
            if workload_cycles is None:
                workload_cycles = t.get("workload")

            input_size = t.get("input_size")
            output_size = t.get("output_size")

            obj = Task.objects.filter(application_type_id=app_type, index=idx).first()
            if obj is None:
                obj = Task.objects.create(
                    application_type_id=app_type,
                    task_type_id=task_type,
                    index=idx,
                    workload_cycles=workload_cycles,
                    input_size=input_size,
                    output_size=output_size,
                )
            else:
                obj.task_type_id = task_type
                obj.workload_cycles = workload_cycles
                obj.input_size = input_size
                obj.output_size = output_size
                obj.save(update_fields=["task_type_id", "workload_cycles", "input_size", "output_size"])

            created_tasks[idx] = obj

        for e in edges_raw:
            if not isinstance(e, dict):
                raise CommandError("Each dependency must be an object")
            p = e.get("parent")
            c = e.get("child")
            if p is None or c is None:
                raise CommandError("Each dependency must have: parent, child")
            pi = int(p)
            ci = int(c)
            if pi not in created_tasks or ci not in created_tasks:
                raise CommandError(f"Dependency refers to missing task index: {pi}->{ci}")

            parent_task = created_tasks[pi]
            child_task = created_tasks[ci]

            exists = TaskDependency.objects.filter(parent_task_id=parent_task, child_task_id=child_task).exists()
            if not exists:
                TaskDependency.objects.create(parent_task_id=parent_task, child_task_id=child_task)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded ApplicationType={app_type.id} tasks={len(created_tasks)} deps={len(edges_raw)} replace={replace}"
        ))
