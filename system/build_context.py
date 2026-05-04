from collections import defaultdict
from application.models import Application
from dag.models import Task, TaskDependency
from object.models import ServiceProvider, Vehicle
from cache.models import cache as Cache
from resource.models import Resource
from parameter.services import load_params_for_lib
from monarch_pylib.model.communication import distance_2d

class MiniSystemContextBuilder:
    def __init__(self, application_id: int):
        self.application_id = int(application_id)
        self.ctx = {"application_id": self.application_id}

    def build_context(self) -> dict:
        self._build_application()
        self._build_task_info()
        self._build_providers()
        self._build_network_state()
        self._build_cache_state()
        self._build_assignment_state()
        self._build_auxiliary_fields()
        return self.ctx

    def _build_application(self):
        app = Application.objects.select_related("application_type_id", "vehicle_id").get(id=self.application_id)
        self.ctx["application"] = {"id": app.id, "application_type_id": app.application_type_id.id}
        ddl = float(app.application_type_id.deadline)
        self.ctx["t_ddl_s"] = ddl
        self.ctx["deadline_s"] = ddl
        self.ctx["deadline_max_s"] = ddl
        self.ctx["vehicle_id"] = app.vehicle_id.id if app.vehicle_id else None

    def _build_task_info(self):
        app_type_id = self.ctx["application"]["application_type_id"]
        tasks = list(Task.objects.filter(application_type_id=app_type_id).select_related("task_type_id").order_by("id"))
        tids = [t.id for t in tasks]
        self.ctx["task_ids"] = tids
        self.ctx["cpu_cycles"] = {t.id: float(t.workload_cycles) for t in tasks}
        self.ctx["task_type_ids"] = {t.id: (t.task_type_id.id if t.task_type_id else None) for t in tasks}
        self.ctx["task_type_size_bits"] = {t.id: (int(t.task_type_id.size) * 8 if t.task_type_id else 0) for t in tasks}
        deps = defaultdict(list)
        children = defaultdict(list)
        for d in TaskDependency.objects.filter(parent_task_id_id__in=tids, child_task_id_id__in=tids):
            deps[d.child_task_id_id].append(d.parent_task_id_id)
            children[d.parent_task_id_id].append(d.child_task_id_id)
        self.ctx["dependencies"] = dict(deps)
        self.ctx["children"] = dict(children)
        ready = [t for t in tids if not deps[t]]
        self.ctx["tasks"] = {"all": tids, "ready": ready}

    def _build_providers(self):
        app = Application.objects.get(id=self.application_id)
        providers = (app.context or {}).get("available_sps", [])
        self.ctx["providers"] = list(providers)
        self.ctx["sp_cpu_freq"] = {}
        self.ctx["sp_cache_capacity"] = {}
        self.ctx["sp_types"] = {}
        self.ctx["sp_position"] = {}
        for sp in ServiceProvider.objects.filter(id__in=providers):
            res = Resource.objects.filter(sp_id=sp.id).first()
            self.ctx["sp_cpu_freq"][sp.id] = float(res.cpu_capacity if res else 1e9)
            self.ctx["sp_cache_capacity"][sp.id] = int(res.cache_capacity if res else 0)
            self.ctx["sp_types"][sp.id] = sp.type
            if sp.type == "rsu":
                self.ctx["sp_position"][sp.id] = (sp.rsu_id.x_coord, sp.rsu_id.y_coord)
            else:
                self.ctx["sp_position"][sp.id] = (sp.vehicle_id.x_coord, sp.vehicle_id.y_coord)

    def _build_network_state(self):
        params_lib = load_params_for_lib()
        app_vehicle = None
        if self.ctx.get("vehicle_id"):
            app_vehicle = Vehicle.objects.filter(id=self.ctx["vehicle_id"]).first()
        if app_vehicle:
            vx, vy = app_vehicle.x_coord, app_vehicle.y_coord
            v_speed = app_vehicle.speed
            local_cpu = float(app_vehicle.cpu_capacity)
        else:
            vx, vy, v_speed, local_cpu = 0.0, 0.0, 0.0, float(params_lib.fmax_vehicle_hz)

        distances = {}
        for sp in self.ctx["providers"]:
            sx, sy = self.ctx["sp_position"][sp]
            distances[sp] = distance_2d(vx, vy, sx, sy)

        self.ctx["distance"] = distances
        self.ctx["v_m"] = {sp: float(v_speed) for sp in self.ctx["providers"]}
        self.ctx["local_cpu_freq_hz"] = float(local_cpu)
        self.ctx["p_n_w"] = {sp: float(params_lib.pmax_vehicle_w * 0.1) for sp in self.ctx["providers"]}

    def _build_cache_state(self):
        self.ctx["cache"] = {
            sp: set(Cache.objects.filter(sp_id_id=sp).values_list("task_type_id_id", flat=True))
            for sp in self.ctx["providers"]
        }

    def _build_assignment_state(self):
        tids = self.ctx["task_ids"]
        self.ctx["z"] = {"binary": {}, "compact": {t: {"provider": None, "rank": None} for t in tids}}

    def _build_auxiliary_fields(self):
        self.ctx["idle_time"] = 0.0
        self.ctx["output_size"] = {t: self.ctx["task_type_size_bits"][t] for t in self.ctx["task_ids"]}
        task_types = set(self.ctx["task_type_ids"].values()) - {None}
        self.ctx["compile_workloads"] = {
            k: sum(self.ctx["cpu_cycles"][t] for t in self.ctx["task_ids"] if self.ctx["task_type_ids"][t] == k)
            for k in task_types
        }
