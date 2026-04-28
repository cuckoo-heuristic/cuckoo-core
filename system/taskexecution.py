def build_taskexecution(ctx, write_db=False):
    ctx["task_executions"] = []
    ctx["done_task_ids"] = []
    ctx["running_task_ids"] = []
    return ctx
