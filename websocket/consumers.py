import json
from channels.generic.websocket import AsyncWebsocketConsumer
from task.models import Task
from vehicle.models import Vehicle
import asyncio

class VehicleStatusConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.vehicle_id = self.scope['url_route']['kwargs']['vehicle_id']
        await self.accept()

        while True:
            await self.send_status()
            await asyncio.sleep(2)

    async def send_status(self):
        try:
            vehicle = await asyncio.to_thread(Vehicle.objects.get, id=self.vehicle_id)
        except Vehicle.DoesNotExist:
            await self.send(json.dumps({"error": "vehicle not found"}))
            return

        task = Task.objects.filter(vehicle=vehicle, is_active=True).first()

        if task:
            data = {
                "vehicle_id": vehicle.id,
                "task": task.description
            }
        else:
            data = {
                "vehicle_id": vehicle.id,
                "task": None
            }

        await self.send(json.dumps(data))
