from highrise import BaseBot, __main__

class Bot(BaseBot):
    async def on_start(self, session_metadata):
        print("Bot odaya katıldı!")

    async def on_chat(self, user, message):
        print(f"{user.username}: {message}")

    async def on_user_join(self, user):
        print(f"{user.username} odaya katıldı.")

    async def on_user_leave(self, user):
        print(f"{user.username} odadan ayrıldı.")


if __name__ == "__main__":
    room_id = "67a8a35c3c5e0a796e05dfef"
    api_key = "7394308cbc3189d365774c71c74758068269f7d00164c05edd6662644518fef2"

    import sys
    sys.argv = ["main", "bot:Bot", room_id, api_key]
    __main__.main()
