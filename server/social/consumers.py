from channels.generic.websocket import AsyncJsonWebsocketConsumer

class LeaderboardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        await self.channel_layer.group_add("lb.all", self.channel_name)           
        if user and user.is_authenticated:
            await self.channel_layer.group_add(f"lb.friends.{user.id}", self.channel_name) 
        await self.accept()

    async def disconnect(self, code):
        user = self.scope.get("user")
        await self.channel_layer.group_discard("lb.all", self.channel_name)
        if user and user.is_authenticated:
            await self.channel_layer.group_discard(f"lb.friends.{user.id}", self.channel_name)  


    async def lb_changed_all(self, event):
        await self.send_json({"type": "lb_changed_all"})

    async def lb_changed_friends(self, event):
        await self.send_json({"type": "lb_changed_friends"})
