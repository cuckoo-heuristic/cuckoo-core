from .dcsga import DCSGA
from .dtosc import DTOSC
from .to_v2i import TO_V2I
from .to_wo_c import TO_WO_C
from .to_wo_r import TO_WO_R


PAPER_ALGORITHMS = {
    "dcsga": DCSGA(),
    "dtosc": DTOSC(),
    "to_v2i": TO_V2I(),
    "to_wo_c": TO_WO_C(),
    "to_wo_r": TO_WO_R(),
}

PAPER_ALGORITHM_NAMES = tuple(PAPER_ALGORITHMS)


JOINT_BENCHMARK_ALGORITHMS = dict(PAPER_ALGORITHMS)

JOINT_BENCHMARK_ALGORITHM_NAMES = tuple(JOINT_BENCHMARK_ALGORITHMS)
