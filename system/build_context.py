from __future__ import annotations
from typing import Dict, Any

# import new modular pipeline builders
from system.application import build_application
from system.resource import build_resource
from system.cache import build_cache_state
from system.state import build_state
from system.taskexecution import build_taskexecution


class MiniSystemContextBuilder:
    """
    New lightweight wrapper that delegates context-building
    to the modular pipeline system (system/*.py).
    """

    def __init__(self, application_id: int):
        self.application_id = application_id
        self.context: Dict[str, Any] = {
            "application_id": application_id
        }

    # -----------------------------------------------------
    # Modern build_context orchestrator
    # -----------------------------------------------------
    def build_context(self):
        """
        The new MiniSystemContextBuilder simply calls the modular
        pipeline builder functions in the correct order.
        """
        # 1) Radio/State must run first (depending on your logic)
        self.context = build_state(self.context)

        # 2) Resource providers
        self.context = build_resource(self.context)

        # 3) Application + tasks + DAG + Z + X + workloads
        self.context = build_application(self.context)

        # 4) Cache state
        self.context = build_cache_state(self.context)

        # 5) Task execution
        self.context = build_taskexecution(self.context)

        return self.context
