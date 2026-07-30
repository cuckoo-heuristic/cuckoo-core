"""Compatibility entry point for the canonical GAC-DJaya implementation.

The optimizer itself lives in ``algorithm.new_algorithm``.  Benchmark code no
longer maintains an independent copy of initialization, GA or Jaya logic.
"""

from algorithm.new_algorithm.joint_gac_djaya import run_joint_gac_djaya

__all__ = ["run_joint_gac_djaya"]
