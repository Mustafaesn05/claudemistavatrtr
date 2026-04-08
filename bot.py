import json
import os
from highrise import BaseBot, __main__
from highrise.models import User

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
ROLES_FILE = os.path.join(DATA_DIR, "roles.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_roles():
    return load_json(ROLES_FILE, {})


def save_roles(roles):
    save_json(ROLES_FILE, roles)


def load_settings():
    return load_json(SETTINGS_FILE, {
        "welcome_message": "Hoş geldin! 🎉",
        "welcome_mode": "chat"
    })


def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


def has_role(username, role):
    roles = load_roles()
    user_roles = roles.get(username, [])
    return role in user_roles


def is_host(username):
    return has_role(username, "host")


class Bot(BaseBot):
    async def on_start(self, session_metadata):
        print("Bot odaya katıldı!")

    async def on_user_join(self, user):
        settings = load_settings()
        msg = settings.get("welcome_message", "Hoş geldin! 🎉")
        welcome_text = msg.replace("{user}", user.username)
        mode = settings.get("welcome_mode", "chat")

        if mode == "whisper":
            await self.highrise.send_whisper(user.id, welcome_text)
        else:
            await self.highrise.chat(f"{user.username}, {welcome_text}")

    async def on_chat(self, user, message):
        msg = message.strip()

        if not msg.startswith("!"):
            return

        parts = msg.split(None, 2)
        cmd = parts[0].lower()

        # --- !welcome komutu (sadece host) ---
        if cmd == "!welcome":
            if not is_host(user.username):
                await self.highrise.chat("❌ Bu komutu sadece hostlar kullanabilir.")
                return

            if len(parts) < 2:
                settings = load_settings()
                current_msg = settings.get("welcome_message", "Hoş geldin! 🎉")
                current_mode = settings.get("welcome_mode", "chat")
                await self.highrise.chat(
                    f"📋 Mevcut hoş geldin mesajı: {current_msg}\n"
                    f"📋 Gönderim modu: {current_mode}"
                )
                return

            sub = parts[1].lower()

            if sub == "whisper":
                settings = load_settings()
                settings["welcome_mode"] = "whisper"
                save_settings(settings)
                await self.highrise.chat("✅ Hoş geldin mesajı artık whisper olarak gönderilecek.")
                return

            if sub == "chat":
                settings = load_settings()
                settings["welcome_mode"] = "chat"
                save_settings(settings)
                await self.highrise.chat("✅ Hoş geldin mesajı artık chat olarak gönderilecek.")
                return

            # !welcome <mesaj> — mesajı değiştir
            new_message = msg[len("!welcome "):]
            settings = load_settings()
            settings["welcome_message"] = new_message
            save_settings(settings)
            await self.highrise.chat(f"✅ Hoş geldin mesajı güncellendi: {new_message}")
            return

        # --- !give komutu (sadece host) ---
        if cmd == "!give":
            if not is_host(user.username):
                await self.highrise.chat("❌ Bu komutu sadece hostlar kullanabilir.")
                return

            if len(parts) < 3:
                await self.highrise.chat("❌ Kullanım: !give @kullanıcıadı host,admin,vip")
                return

            target = parts[1].lstrip("@")
            role_list = [r.strip().lower() for r in parts[2].split(",")]
            valid_roles = {"host", "admin", "vip"}
            invalid = [r for r in role_list if r not in valid_roles]
            if invalid:
                await self.highrise.chat(f"❌ Geçersiz roller: {', '.join(invalid)}. Geçerli: host, admin, vip")
                return

            roles = load_roles()
            if target not in roles:
                roles[target] = []
            added = []
            for r in role_list:
                if r not in roles[target]:
                    roles[target].append(r)
                    added.append(r)
            save_roles(roles)

            if added:
                await self.highrise.chat(f"✅ {target} kullanıcısına {', '.join(added)} rolü verildi.")
            else:
                await self.highrise.chat(f"ℹ️ {target} zaten bu rollere sahip.")
            return

        # --- !remove komutu (sadece host) ---
        if cmd == "!remove":
            if not is_host(user.username):
                await self.highrise.chat("❌ Bu komutu sadece hostlar kullanabilir.")
                return

            if len(parts) < 3:
                await self.highrise.chat("❌ Kullanım: !remove @kullanıcıadı host,admin,vip")
                return

            target = parts[1].lstrip("@")
            role_list = [r.strip().lower() for r in parts[2].split(",")]
            valid_roles = {"host", "admin", "vip"}
            invalid = [r for r in role_list if r not in valid_roles]
            if invalid:
                await self.highrise.chat(f"❌ Geçersiz roller: {', '.join(invalid)}. Geçerli: host, admin, vip")
                return

            roles = load_roles()
            if target not in roles:
                await self.highrise.chat(f"ℹ️ {target} kullanıcısının hiç rolü yok.")
                return

            removed = []
            for r in role_list:
                if r in roles[target]:
                    roles[target].remove(r)
                    removed.append(r)
            if not roles[target]:
                del roles[target]
            save_roles(roles)

            if removed:
                await self.highrise.chat(f"✅ {target} kullanıcısından {', '.join(removed)} rolü alındı.")
            else:
                await self.highrise.chat(f"ℹ️ {target} zaten bu rollere sahip değil.")
            return

    async def on_user_leave(self, user):
        print(f"{user.username} odadan ayrıldı.")


if __name__ == "__main__":
    room_id = "67a8a35c3c5e0a796e05dfef"
    api_key = "7394308cbc3189d365774c71c74758068269f7d00164c05edd6662644518fef2"

    import sys
    sys.argv = ["main", "bot:Bot", room_id, api_key]
    __main__.main()
