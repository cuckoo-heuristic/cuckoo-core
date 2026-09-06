from .dcsga import DCSGA
from .dtosc import DTOSC
from .to_v2i import TO_V2I
from .to_wo_c import TO_WO_C
from .to_wo_r import TO_WO_R
from .gwo_aco import GWO_ACO
from .pso import PSO
from .gpc import GPC


ALL_ALGORITHMS = {
    "dcsga": DCSGA(),
    "dtosc": DTOSC(),
    "to_v2i": TO_V2I(),
    "to_wo_c": TO_WO_C(),
    "to_wo_r": TO_WO_R(),
    "gwo_aco": GWO_ACO(),
    "pso": PSO(),
    "gpc": GPC(),
}

PAPER_ALGORITHM_NAMES = (
    "dcsga",
    "dtosc",
    "to_v2i",
    "to_wo_c",
    "to_wo_r",
)
PAPER_ALGORITHMS = {
    name: ALL_ALGORITHMS[name] for name in PAPER_ALGORITHM_NAMES
}

JOINT_BENCHMARK_ALGORITHMS = dict(ALL_ALGORITHMS)

JOINT_BENCHMARK_ALGORITHM_NAMES = tuple(JOINT_BENCHMARK_ALGORITHMS)
