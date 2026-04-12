import json
import os
import re
import asyncio
from highrise import BaseBot, __main__
from highrise.models import User, Position

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
ROLES_FILE = os.path.join(DATA_DIR, "roles.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
LANGS_DIR = os.path.join(DATA_DIR, "langs")
EMOTES_FILE = os.path.join(DATA_DIR, "emotes.json")
TELEPORTS_FILE = os.path.join(DATA_DIR, "teleports.json")

SUPPORTED_LANGS = {"tr", "en", "ar", "ru", "de"}
ROLE_HIERARCHY = {"vip": 1, "admin": 2, "host": 3}


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
        "welcome_message": "",
        "welcome_mode": "chat",
        "lang": "tr"
    })


def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


def load_lang(lang_code):
    path = os.path.join(LANGS_DIR, f"{lang_code}.json")
    return load_json(path, {})


def load_emotes():
    return load_json(EMOTES_FILE, {})


def t(key, **kwargs):
    settings = load_settings()
    lang_code = settings.get("lang", "tr")
    lang = load_lang(lang_code)
    text = lang.get(key, key)
    if kwargs:
        text = text.format(**kwargs)
    return text


def has_role(username, role):
    roles = load_roles()
    user_roles = roles.get(username, [])
    return role in user_roles


def is_host(username):
    return has_role(username, "host")


def has_role_level(username, required_role):
    """Check if user has the required role level or higher."""
    roles = load_roles()
    user_roles = roles.get(username, [])
    required_level = ROLE_HIERARCHY.get(required_role, 0)
    for role in user_roles:
        if ROLE_HIERARCHY.get(role, 0) >= required_level:
            return True
    return False


def is_admin_or_above(username):
    return has_role_level(username, "admin")


def load_teleports():
    return load_json(TELEPORTS_FILE, {})


def save_teleports(teleports):
    save_json(TELEPORTS_FILE, teleports)


def find_emote(query):
    """Emote'u numara veya isimle bul."""
    emotes = load_emotes()
    query_lower = query.lower()

    # Numarayla ara
    if query in emotes:
        return emotes[query]

    # İsimle ara
    for num, emote in emotes.items():
        if emote["name"].lower() == query_lower:
            return emote

    return None


class Bot(BaseBot):
    def __init__(self):
        super().__init__()
        # user_id -> asyncio.Task (loop halinde emote gönderen task)
        self.emote_loops = {}

    async def on_start(self, session_metadata):
        print("Bot odaya katıldı!")
        settings = load_settings()
        bot_spawn = settings.get("bot_spawn")
        if bot_spawn:
            try:
                await self.highrise.walk_to(Position(bot_spawn["x"], bot_spawn["y"], bot_spawn["z"]))
            except Exception:
                pass

    async def on_user_join(self, user):
        settings = load_settings()
        welcome_msg = settings.get("welcome_message", "")
        if not welcome_msg:
            welcome_msg = t("welcome_default")
        welcome_text = welcome_msg.replace("{user}", user.username)
        mode = settings.get("welcome_mode", "chat")

        if mode == "whisper":
            await self.highrise.send_whisper(user.id, welcome_text)
        else:
            await self.highrise.chat(f"{user.username}, {welcome_text}")

    async def _emote_loop(self, user_id, emote_id, duration):
        """Emote'u kendi süresi bitince tekrar gönderir, iptal edilene kadar."""
        try:
            while True:
                await self.highrise.send_emote(emote_id, user_id)
                await asyncio.sleep(duration)
        except asyncio.CancelledError:
            pass

    def _start_emote_loop(self, user_id, emote):
        """Kullanıcı için emote loop başlat, varsa öncekini iptal et."""
        if user_id in self.emote_loops:
            self.emote_loops[user_id].cancel()
        duration = emote.get("duration", 5)
        task = asyncio.create_task(self._emote_loop(user_id, emote["id"], duration))
        self.emote_loops[user_id] = task

    def _stop_emote_loop(self, user_id):
        """Kullanıcının emote loop'unu durdur."""
        if user_id in self.emote_loops:
            self.emote_loops[user_id].cancel()
            del self.emote_loops[user_id]

    async def _get_user_position(self, user_id):
        """Get a user's current position in the room."""
        response = await self.highrise.get_room_users()
        for room_user, position in response.content:
            if room_user.id == user_id:
                return position
        return None

    async def _find_room_user(self, username):
        """Find a user in the room by username."""
        response = await self.highrise.get_room_users()
        for room_user, position in response.content:
            if room_user.username.lower() == username.lower():
                return room_user, position
        return None, None

    async def on_chat(self, user, message):
        msg = message.strip()

        # stop/dur komutu — emote loop'u durdur
        if msg.lower() in ("stop", "dur"):
            self._stop_emote_loop(user.id)
            await self.highrise.send_whisper(user.id, t("emote_stopped"))
            return

        if not msg.startswith("!"):
            # Önce teleport noktası kontrol et
            teleports = load_teleports()
            tele_key = None
            for key in teleports:
                if key.lower() == msg.lower():
                    tele_key = key
                    break

            if tele_key:
                tele = teleports[tele_key]
                required_role = tele.get("role")
                if required_role and not has_role_level(user.username, required_role):
                    await self.highrise.send_whisper(user.id, t("tele_no_permission"))
                    return
                try:
                    await self.highrise.teleport(user.id, Position(tele["x"], tele["y"], tele["z"]))
                    await self.highrise.send_whisper(user.id, t("tele_teleported", name=tele_key))
                except Exception:
                    pass
                return

            # Sayı veya emote ismi yazıldıysa emote loop başlat
            emote = find_emote(msg)
            if emote:
                self._start_emote_loop(user.id, emote)
                await self.highrise.send_whisper(user.id, t("emote_started", name=emote["name"]))
            return

        parts = msg.split(None, 2)
        cmd = parts[0].lower()

        # --- !create tele <ad> [(rol)] ---
        if cmd == "!create" and len(parts) >= 2 and parts[1].lower() == "tele":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return
            if len(parts) < 3:
                await self.highrise.send_whisper(user.id, t("tele_create_usage"))
                return

            rest = parts[2].strip()
            match = re.match(r'^(\S+)\s*\((\w+)\)$', rest)
            if match:
                tele_name = match.group(1).lower()
                role = match.group(2).lower()
                if role not in ROLE_HIERARCHY:
                    await self.highrise.send_whisper(user.id, t("tele_invalid_role"))
                    return
            else:
                tele_name = rest.split()[0].lower()
                role = None

            teleports = load_teleports()
            if tele_name in teleports:
                await self.highrise.send_whisper(user.id, t("tele_exists", name=tele_name))
                return

            position = await self._get_user_position(user.id)
            if not position:
                return

            teleports[tele_name] = {
                "x": position.x,
                "y": position.y,
                "z": position.z,
                "role": role
            }
            save_teleports(teleports)

            if role:
                await self.highrise.send_whisper(user.id, t("tele_created_role", name=tele_name, role=role))
            else:
                await self.highrise.send_whisper(user.id, t("tele_created", name=tele_name))
            return

        # --- !delete tele <ad> ---
        if cmd == "!delete" and len(parts) >= 2 and parts[1].lower() == "tele":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return
            if len(parts) < 3:
                await self.highrise.send_whisper(user.id, t("tele_delete_usage"))
                return

            tele_name = parts[2].strip().lower()
            teleports = load_teleports()

            actual_key = None
            for key in teleports:
                if key.lower() == tele_name:
                    actual_key = key
                    break

            if not actual_key:
                await self.highrise.send_whisper(user.id, t("tele_not_found", name=tele_name))
                return

            del teleports[actual_key]
            save_teleports(teleports)
            await self.highrise.send_whisper(user.id, t("tele_deleted", name=tele_name))
            return

        # --- !tele @kullanıcı <teleportadı | x y z> ---
        if cmd == "!tele":
            if not is_admin_or_above(user.username):
                await self.highrise.send_whisper(user.id, t("admin_only"))
                return
            if len(parts) < 3:
                await self.highrise.send_whisper(user.id, t("tele_usage"))
                return

            target_name = parts[1].lstrip("@")
            rest = parts[2].strip()

            target_user, target_pos = await self._find_room_user(target_name)
            if not target_user:
                await self.highrise.send_whisper(user.id, t("tele_user_not_found", target=target_name))
                return

            # Koordinat kontrolü (x y z) - sadece host
            coord_parts = rest.split()
            if len(coord_parts) == 3:
                try:
                    x = float(coord_parts[0])
                    y = float(coord_parts[1])
                    z = float(coord_parts[2])
                    if not is_host(user.username):
                        await self.highrise.send_whisper(user.id, t("tele_coord_host_only"))
                        return
                    await self.highrise.teleport(target_user.id, Position(x, y, z))
                    await self.highrise.send_whisper(user.id, t("tele_user_teleported_coord", target=target_name, x=x, y=y, z=z))
                    return
                except ValueError:
                    pass

            # Teleport noktası adıyla ışınla
            tele_name = rest.lower()
            teleports = load_teleports()
            actual_key = None
            for key in teleports:
                if key.lower() == tele_name:
                    actual_key = key
                    break

            if not actual_key:
                await self.highrise.send_whisper(user.id, t("tele_not_found", name=tele_name))
                return

            tele = teleports[actual_key]
            await self.highrise.teleport(target_user.id, Position(tele["x"], tele["y"], tele["z"]))
            await self.highrise.send_whisper(user.id, t("tele_user_teleported", target=target_name, name=actual_key))
            return

        # --- !tp x y z (host kendini koordinatla ışınlar) ---
        if cmd == "!tp":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return

            all_parts = msg.split()
            if len(all_parts) != 4:
                await self.highrise.send_whisper(user.id, t("tp_usage"))
                return

            try:
                x = float(all_parts[1])
                y = float(all_parts[2])
                z = float(all_parts[3])
            except ValueError:
                await self.highrise.send_whisper(user.id, t("tp_usage"))
                return

            await self.highrise.teleport(user.id, Position(x, y, z))
            await self.highrise.send_whisper(user.id, t("tp_teleported", x=x, y=y, z=z))
            return

        # --- !bot (bot başlangıç noktası ayarla) ---
        if cmd == "!bot":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return

            all_parts = msg.split()
            if len(all_parts) == 4:
                try:
                    x = float(all_parts[1])
                    y = float(all_parts[2])
                    z = float(all_parts[3])
                except ValueError:
                    await self.highrise.send_whisper(user.id, t("bot_usage"))
                    return
            elif len(all_parts) == 1:
                position = await self._get_user_position(user.id)
                if not position:
                    return
                x, y, z = position.x, position.y, position.z
            else:
                await self.highrise.send_whisper(user.id, t("bot_usage"))
                return

            settings = load_settings()
            settings["bot_spawn"] = {"x": x, "y": y, "z": z}
            save_settings(settings)

            try:
                await self.highrise.walk_to(Position(x, y, z))
            except Exception:
                pass

            await self.highrise.send_whisper(user.id, t("bot_spawn_set", x=x, y=y, z=z))
            return

        # --- !emote komutu ---
        if cmd == "!emote":
            if len(parts) >= 2 and parts[1].lower() == "list":
                await self._send_emote_list(user.id)
                return

            # !emote <numara/isim> — emote loop başlat
            if len(parts) >= 2:
                query = parts[1]
                emote = find_emote(query)
                if emote:
                    self._start_emote_loop(user.id, emote)
                    await self.highrise.send_whisper(user.id, t("emote_started", name=emote["name"]))
                else:
                    await self.highrise.send_whisper(user.id, t("emote_not_found", query=query))
                return

            await self.highrise.send_whisper(user.id, t("emote_usage"))
            return

        # --- !lang komutu (sadece host) ---
        if cmd == "!lang":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return

            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("lang_usage"))
                return

            lang_code = parts[1].lower()
            if lang_code not in SUPPORTED_LANGS:
                await self.highrise.send_whisper(user.id, t("lang_invalid"))
                return

            settings = load_settings()
            settings["lang"] = lang_code
            settings["welcome_message"] = ""
            save_settings(settings)
            await self.highrise.send_whisper(user.id, t("lang_changed"))
            return

        # --- !welcome komutu (sadece host) ---
        if cmd == "!welcome":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return

            if len(parts) < 2:
                settings = load_settings()
                current_msg = settings.get("welcome_message", "")
                if not current_msg:
                    current_msg = t("welcome_default")
                current_mode = settings.get("welcome_mode", "chat")
                await self.highrise.send_whisper(user.id, t("welcome_info", message=current_msg, mode=current_mode))
                return

            sub = parts[1].lower()

            if sub == "whisper":
                settings = load_settings()
                settings["welcome_mode"] = "whisper"
                save_settings(settings)
                await self.highrise.send_whisper(user.id, t("welcome_mode_whisper"))
                return

            if sub == "chat":
                settings = load_settings()
                settings["welcome_mode"] = "chat"
                save_settings(settings)
                await self.highrise.send_whisper(user.id, t("welcome_mode_chat"))
                return

            new_message = msg[len("!welcome "):]
            settings = load_settings()
            settings["welcome_message"] = new_message
            save_settings(settings)
            await self.highrise.send_whisper(user.id, t("welcome_updated", message=new_message))
            return

        # --- !give komutu (sadece host) ---
        if cmd == "!give":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return

            if len(parts) < 3:
                await self.highrise.send_whisper(user.id, t("give_usage"))
                return

            target = parts[1].lstrip("@")
            role_list = [r.strip().lower() for r in parts[2].split(",")]
            valid_roles = {"host", "admin", "vip"}
            invalid = [r for r in role_list if r not in valid_roles]
            if invalid:
                await self.highrise.send_whisper(user.id, t("invalid_roles", roles=", ".join(invalid)))
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
                await self.highrise.send_whisper(user.id, t("roles_added", target=target, roles=", ".join(added)))
            else:
                await self.highrise.send_whisper(user.id, t("roles_already", target=target))
            return

        # --- !remove komutu (sadece host) ---
        if cmd == "!remove":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("host_only"))
                return

            if len(parts) < 3:
                await self.highrise.send_whisper(user.id, t("remove_usage"))
                return

            target = parts[1].lstrip("@")
            role_list = [r.strip().lower() for r in parts[2].split(",")]
            valid_roles = {"host", "admin", "vip"}
            invalid = [r for r in role_list if r not in valid_roles]
            if invalid:
                await self.highrise.send_whisper(user.id, t("invalid_roles", roles=", ".join(invalid)))
                return

            roles = load_roles()
            if target not in roles:
                await self.highrise.send_whisper(user.id, t("no_roles", target=target))
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
                await self.highrise.send_whisper(user.id, t("roles_removed", target=target, roles=", ".join(removed)))
            else:
                await self.highrise.send_whisper(user.id, t("roles_not_have", target=target))
            return

    async def _send_emote_list(self, user_id):
        """Emote listesini 256 karakteri geçmeyecek şekilde whisper ile parça parça gönderir."""
        emotes = load_emotes()
        lines = []
        for num in sorted(emotes.keys(), key=lambda x: int(x)):
            emote = emotes[num]
            lines.append(f"{num}. {emote['name']}")

        chunks = []
        current_chunk = ""
        for line in lines:
            if current_chunk:
                test = current_chunk + "\n" + line
            else:
                test = line

            if len(test) <= 256:
                current_chunk = test
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line

        if current_chunk:
            chunks.append(current_chunk)

        for chunk in chunks:
            await self.highrise.send_whisper(user_id, chunk)
            await asyncio.sleep(0.5)

    async def on_user_leave(self, user):
        self._stop_emote_loop(user.id)
        print(f"{user.username} odadan ayrıldı.")


if __name__ == "__main__":
    room_id = "67a8a35c3c5e0a796e05dfef"
    api_key = "7394308cbc3189d365774c71c74758068269f7d00164c05edd6662644518fef2"

    import sys
    sys.argv = ["main", "bot:Bot", room_id, api_key]
    __main__.main()
