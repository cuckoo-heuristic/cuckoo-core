from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from django.core.management.base import BaseCommand, CommandError

from run.baselines import JOINT_BENCHMARK_ALGORITHM_NAMES
from run.benchmark.context import (
    build_joint_context,
    joint_context_summary,
)
from run.benchmark.runner import run_joint_benchmark


class Command(BaseCommand):
    help = (
        "Run the isolated joint benchmark without modifying workers, "
        "simulation state, or TaskExecution rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--application-ids",
            nargs="+",
            type=int,
            required=True,
            help="Application IDs belonging to distinct mission vehicles.",
        )
        parser.add_argument(
            "--algorithms",
            nargs="+",
            default=list(JOINT_BENCHMARK_ALGORITHM_NAMES),
            choices=list(JOINT_BENCHMARK_ALGORITHM_NAMES),
            help="Algorithms included in the joint comparison.",
        )
        parser.add_argument(
            "--seeds",
            nargs="+",
            type=int,
            default=[1],
        )
        parser.add_argument("--tmax", type=int, default=10)
        parser.add_argument(
            "--population-size",
            type=int,
            default=None,
            help="Optional smoke-test override. Omit it to use Parameter.S.",
        )
        parser.add_argument(
            "--max-function-evaluations",
            type=int,
            default=None,
            help="Optional exact objective-evaluation budget for population algorithms.",
        )
        parser.add_argument(
            "--context-only",
            action="store_true",
            help="Build and validate the joint context without running algorithms.",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Optional JSON output file path.",
        )
        parser.add_argument("--indent", type=int, default=2)

    def _write_result(
        self,
        result: Dict[str, Any],
        output: str | None,
        indent: int,
    ) -> None:
        payload = json.dumps(
            result,
            ensure_ascii=False,
            indent=max(0, int(indent)),
            sort_keys=False,
        )

        if output:
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Joint benchmark saved to: {path}"))
        else:
            self.stdout.write(payload)

    def handle(self, *args, **options):
        application_ids = options["application_ids"]
        output = options.get("output")
        indent = options.get("indent", 2)

        try:
            if options.get("context_only"):
                joint_ctx = build_joint_context(application_ids)
                result = {
                    "scientific_stage": "joint-stage-3a-cpu-context-check",
                    "context": joint_context_summary(joint_ctx),
                }
            else:
                result = run_joint_benchmark(
                    application_ids,
                    algorithms=options.get("algorithms"),
                    seeds=options.get("seeds"),
                    tmax=options.get("tmax", 10),
                    population_size=options.get("population_size"),
                    max_function_evaluations=options.get(
                        "max_function_evaluations"
                    ),
                )
        except (ValueError, KeyError, TypeError) as exc:
            raise CommandError(str(exc)) from exc

        self._write_result(result, output, indent)
