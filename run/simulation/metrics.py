# NOTE:
# Metrics are provided only for sanity-check in simulation v1.
# They are NOT intended for benchmarking or algorithm comparison yet.
from typing import Dict, Any, List

def summarize_metrics(timeline):
    latencies, qds = [], []
    task_count = finished = dropped = 0

    for fr in timeline:
        for t in fr.get("tasks", []):
            task_count += 1
            if t.get("decision") == "dropped" or t.get("end_at") is None or t.get("start_at") is None:
                dropped += 1
                continue
            finished += 1
            latencies.append(float(t["end_at"]) - float(t["created_at"]))
            qds.append(float(t.get("queue_delay") or 0.0))

    latencies.sort()
    n = len(latencies)
    p95 = latencies[int(0.95 * (n - 1))] if n else 0.0

    return {
        "task_count": task_count,
        "finished": finished,
        "dropped": dropped,
        "completion_rate": (finished / task_count) if task_count else 0.0,
        "avg_latency": (sum(latencies) / n) if n else 0.0,
        "p95_latency": p95,
        "avg_queue_delay": (sum(qds) / len(qds)) if qds else 0.0,
    }
