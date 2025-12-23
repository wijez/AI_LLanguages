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


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        
        if not user or not user.is_authenticated:
            await self.close(code=4003) 
            return
        
        self.group_name = f"user_{user.id}"
    
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def notify(self, event):
        await self.send_json(event["data"])
