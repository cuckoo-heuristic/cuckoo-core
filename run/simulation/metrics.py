from typing import Dict, Any, List


def summarize_metrics(timeline: List[dict]) -> Dict[str, Any]:
    """
    از روی timeline متریک‌های اصلی را حساب می‌کند.
    """
    tasks = []
    for frame in timeline:
        tasks.extend(frame.get("tasks", []))

    if not tasks:
        return {
            "task_count": 0,
            "completion_rate": None,
            "avg_latency": None,
            "p95_latency": None,
            "avg_queue_delay": None,
            "dropped": 0,
        }

    finished = [t for t in tasks if "end_at" in t]
    dropped = [t for t in tasks if t.get("decision") == "dropped"]

    task_count = len(tasks)
    completion_rate = (len(finished) / task_count) if task_count else None

    latencies = []
    queue_delays = []
    for t in finished:
        latencies.append(float(t["end_at"]) - float(t["created_at"]))
        queue_delays.append(float(t.get("queue_delay", 0.0)))

    latencies_sorted = sorted(latencies)
    p95 = None
    if latencies_sorted:
        idx = int(0.95 * (len(latencies_sorted) - 1))
        p95 = latencies_sorted[idx]

    avg_latency = (sum(latencies) / len(latencies)) if latencies else None
    avg_queue = (sum(queue_delays) / len(queue_delays)) if queue_delays else None

    return {
        "task_count": task_count,
        "finished": len(finished),
        "dropped": len(dropped),
        "completion_rate": completion_rate,
        "avg_latency": avg_latency,
        "p95_latency": p95,
        "avg_queue_delay": avg_queue,
    }
