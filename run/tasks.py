import asyncio
import random
from task.models import Task
from vehicle.models import Vehicle

async def assign_random_task():
    while True:
        vehicles = await asyncio.to_thread(list, Vehicle.objects.all())
        tasks = ["Delivery A", "Delivery B", "Pickup C", "Maintenance D"]

        if vehicles:
            vehicle = random.choice(vehicles)
            task_desc = random.choice(tasks)
            await asyncio.to_thread(Task.objects.create, vehicle=vehicle, description=task_desc, is_active=True)

        await asyncio.sleep(5)
