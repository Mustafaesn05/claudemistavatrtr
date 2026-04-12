import json
import os
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
        "lang": "tr",
        "bot_position": None,
        "loop_message": "",
        "loop_interval": 30
    })


def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


def load_lang(lang_code):
    path = os.path.join(LANGS_DIR, f"{lang_code}.json")
    return load_json(path, {})


def load_emotes():
    return load_json(EMOTES_FILE, {})


def load_teleports():
    return load_json(TELEPORTS_FILE, {})


def save_teleports(data):
    save_json(TELEPORTS_FILE, data)


def t(key, *args):
    settings = load_settings()
    lang_code = settings.get("lang", "tr")
    lang = load_lang(lang_code)
    text = lang.get(key, key)
    if args:
        try:
            text = text.format(*args)
        except (IndexError, KeyError):
            pass
    return text


def has_role(username, role):
    roles = load_roles()
    user_roles = roles.get(username, [])
    return role in user_roles


def is_host(username):
    return has_role(username, "host")


def is_admin(username):
    return has_role(username, "admin") or is_host(username)


def is_vip(username):
    return has_role(username, "vip") or is_admin(username)


def find_emote(query):
    emotes = load_emotes()
    query_lower = query.lower()
    if query in emotes:
        return emotes[query]
    for num, emote in emotes.items():
        if emote["name"].lower() == query_lower:
            return emote
    return None


def find_teleport(name):
    teleports = load_teleports()
    name_lower = name.lower()
    for tele_name, tele_data in teleports.items():
        if tele_name.lower() == name_lower:
            return tele_name, tele_data
    return None, None


class Bot(BaseBot):
    def __init__(self):
        super().__init__()
        self.emote_loops = {}
        self.user_positions = {}
        self.bot_id = None

    async def on_start(self, session_metadata):
        self.bot_id = session_metadata.user_id
        print("Bot started!")
        # Bot başlangıç pozisyonuna git
        settings = load_settings()
        bot_pos = settings.get("bot_position")
        if bot_pos:
            try:
                pos = Position(bot_pos["x"], bot_pos["y"], bot_pos["z"], facing=bot_pos.get("facing", "FrontRight"))
                await self.highrise.walk_to(pos)
            except Exception:
                pass

    async def on_user_join(self, user):
        # Kullanıcı pozisyonlarını güncelle
        try:
            room_users = await self.highrise.get_room_users()
            for u, pos in room_users.content:
                if u.id == user.id and pos:
                    self.user_positions[user.id] = pos
                    break
        except Exception:
            pass

        settings = load_settings()
        welcome_msg = settings.get("welcome_message", "")
        if not welcome_msg:
            welcome_msg = t("welcome_default")
        welcome_text = welcome_msg.replace("{username}", user.username).replace("{user}", user.username)
        mode = settings.get("welcome_mode", "chat")

        if mode == "whisper":
            await self.highrise.send_whisper(user.id, welcome_text)
        else:
            await self.highrise.chat(f"{user.username}, {welcome_text}")

    async def on_user_move(self, user, position):
        if position:
            self.user_positions[user.id] = position

    async def on_user_leave(self, user):
        self._stop_emote_loop(user.id)
        self.user_positions.pop(user.id, None)

    # ---- Emote Loop ----
    async def _emote_loop(self, user_id, emote_id, duration):
        try:
            while True:
                await self.highrise.send_emote(emote_id, user_id)
                await asyncio.sleep(duration)
        except asyncio.CancelledError:
            pass

    def _start_emote_loop(self, user_id, emote):
        if user_id in self.emote_loops:
            self.emote_loops[user_id].cancel()
        duration = emote.get("duration", 5)
        task = asyncio.create_task(self._emote_loop(user_id, emote["id"], duration))
        self.emote_loops[user_id] = task

    def _stop_emote_loop(self, user_id):
        if user_id in self.emote_loops:
            self.emote_loops[user_id].cancel()
            del self.emote_loops[user_id]

    # ---- Yardımcılar ----
    async def _get_user_by_username(self, username):
        try:
            room_users = await self.highrise.get_room_users()
            for u, pos in room_users.content:
                if u.username.lower() == username.lower():
                    return u, pos
        except Exception:
            pass
        return None, None

    async def _get_my_position(self, user_id):
        if user_id in self.user_positions:
            return self.user_positions[user_id]
        try:
            room_users = await self.highrise.get_room_users()
            for u, pos in room_users.content:
                if u.id == user_id and pos:
                    self.user_positions[user_id] = pos
                    return pos
        except Exception:
            pass
        return None

    # ---- Ana Chat Handler ----
    async def on_chat(self, user, message):
        msg = message.strip()

        # stop/dur — emote loop durdur
        if msg.lower() in ("stop", "dur"):
            self._stop_emote_loop(user.id)
            await self.highrise.send_whisper(user.id, t("emote_loop_stopped"))
            return

        if not msg.startswith("!"):
            # Emote ismi/numarası kontrolü
            emote = find_emote(msg)
            if emote:
                self._start_emote_loop(user.id, emote)
                await self.highrise.send_whisper(user.id, t("emote_loop_message", emote["name"]))
                return

            # Teleport noktası adı yazıldıysa ışınla
            tele_name, tele_data = find_teleport(msg)
            if tele_name and tele_data:
                allowed = tele_data.get("allowed_roles", [])
                if allowed:
                    user_roles = load_roles().get(user.username, [])
                    has_access = any(r in user_roles for r in allowed)
                    if not has_access:
                        await self.highrise.send_whisper(user.id, t("teleport_not_allowed", tele_name))
                        return
                try:
                    pos = Position(tele_data["x"], tele_data["y"], tele_data["z"], facing=tele_data.get("facing", "FrontRight"))
                    await self.highrise.teleport(user.id, pos)
                    await self.highrise.send_whisper(user.id, t("teleported_to_location", tele_name))
                except Exception as e:
                    await self.highrise.send_whisper(user.id, t("teleport_error", str(e)))
                return
            return

        # Komut ayrıştırma
        parts = msg.split()
        cmd = parts[0].lower()

        # ---- !create tele <name> [roles] ----
        if cmd == "!create" and len(parts) >= 3 and parts[1].lower() == "tele":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_create_teleport"))
                return

            tele_name = parts[2]
            allowed_roles = []
            if len(parts) >= 4:
                allowed_roles = [r.strip().lower() for r in parts[3].split(",")]

            teleports = load_teleports()
            if tele_name.lower() in [k.lower() for k in teleports]:
                await self.highrise.send_whisper(user.id, t("teleport_name_exists"))
                return

            pos = await self._get_my_position(user.id)
            if not pos:
                await self.highrise.send_whisper(user.id, t("position_not_found"))
                return

            teleports[tele_name] = {
                "x": pos.x,
                "y": pos.y,
                "z": pos.z,
                "facing": getattr(pos, "facing", "FrontRight"),
                "allowed_roles": allowed_roles
            }
            save_teleports(teleports)

            if allowed_roles:
                await self.highrise.send_whisper(user.id, t("teleport_created_with_roles", tele_name, ", ".join(allowed_roles)))
            else:
                await self.highrise.send_whisper(user.id, t("teleport_created", tele_name))
            return

        # ---- !delete tele <name> ----
        if cmd == "!delete" and len(parts) >= 3 and parts[1].lower() == "tele":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_delete_teleport"))
                return

            tele_name = parts[2]
            teleports = load_teleports()
            found_key = None
            for k in teleports:
                if k.lower() == tele_name.lower():
                    found_key = k
                    break

            if not found_key:
                await self.highrise.send_whisper(user.id, t("teleport_not_found", tele_name))
                return

            del teleports[found_key]
            save_teleports(teleports)
            await self.highrise.send_whisper(user.id, t("teleport_deleted", found_key))
            return

        # ---- !tele ----
        if cmd == "!tele":
            if not is_vip(user.username):
                await self.highrise.send_whisper(user.id, t("only_vip_and_above_teleport"))
                return

            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_teleport"))
                return

            # !tele @user ...
            if parts[1].startswith("@"):
                target_name = parts[1].lstrip("@")

                if len(parts) == 2:
                    # !tele @user — kullanıcının yanına ışınlan
                    target_user, target_pos = await self._get_user_by_username(target_name)
                    if not target_user:
                        await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                        return
                    if not target_pos:
                        await self.highrise.send_whisper(user.id, t("position_not_found"))
                        return
                    try:
                        await self.highrise.teleport(user.id, target_pos)
                        await self.highrise.send_whisper(user.id, t("teleported_to_user", target_name))
                        await self.highrise.send_whisper(target_user.id, t("user_teleported_to_you", user.username))
                    except Exception as e:
                        await self.highrise.send_whisper(user.id, t("teleport_error", str(e)))
                    return

                # !tele @user x y z
                if len(parts) == 5:
                    if not is_host(user.username):
                        await self.highrise.send_whisper(user.id, t("only_hosts_create_teleport"))
                        return
                    try:
                        x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
                    except ValueError:
                        await self.highrise.send_whisper(user.id, t("invalid_coordinates"))
                        return

                    target_user, _ = await self._get_user_by_username(target_name)
                    if not target_user:
                        await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                        return
                    try:
                        pos = Position(x, y, z, facing="FrontRight")
                        await self.highrise.teleport(target_user.id, pos)
                        await self.highrise.send_whisper(user.id, t("user_teleported_to_coords", target_name, x, y, z))
                        await self.highrise.send_whisper(target_user.id, t("teleported_by_user_to_coords", user.username, x, y, z))
                    except Exception as e:
                        await self.highrise.send_whisper(user.id, t("teleport_error", str(e)))
                    return

                # !tele @user <teleport_name>
                if len(parts) == 3:
                    if not is_admin(user.username):
                        await self.highrise.send_whisper(user.id, t("only_vip_and_above_teleport"))
                        return
                    tele_name, tele_data = find_teleport(parts[2])
                    if not tele_name:
                        await self.highrise.send_whisper(user.id, t("teleport_not_found", parts[2]))
                        return
                    target_user, _ = await self._get_user_by_username(target_name)
                    if not target_user:
                        await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                        return
                    try:
                        pos = Position(tele_data["x"], tele_data["y"], tele_data["z"], facing=tele_data.get("facing", "FrontRight"))
                        await self.highrise.teleport(target_user.id, pos)
                        await self.highrise.send_whisper(user.id, t("user_teleported_to_location", target_name, tele_name))
                        await self.highrise.send_whisper(target_user.id, t("teleported_by_user", tele_name, user.username))
                    except Exception as e:
                        await self.highrise.send_whisper(user.id, t("teleport_error", str(e)))
                    return

                await self.highrise.send_whisper(user.id, t("usage_teleport"))
                return

            # !tele x y z
            if len(parts) == 4:
                try:
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                except ValueError:
                    # Belki teleport adı + birşey
                    await self.highrise.send_whisper(user.id, t("invalid_coordinates"))
                    return
                try:
                    pos = Position(x, y, z, facing="FrontRight")
                    await self.highrise.teleport(user.id, pos)
                    await self.highrise.send_whisper(user.id, t("teleported_to_coords", x, y, z))
                except Exception as e:
                    await self.highrise.send_whisper(user.id, t("teleport_error", str(e)))
                return

            # !tele <name>
            if len(parts) == 2:
                tele_name, tele_data = find_teleport(parts[1])
                if not tele_name:
                    await self.highrise.send_whisper(user.id, t("teleport_not_found", parts[1]))
                    return
                allowed = tele_data.get("allowed_roles", [])
                if allowed:
                    user_roles = load_roles().get(user.username, [])
                    has_access = any(r in user_roles for r in allowed)
                    if not has_access:
                        await self.highrise.send_whisper(user.id, t("teleport_not_allowed", tele_name))
                        return
                try:
                    pos = Position(tele_data["x"], tele_data["y"], tele_data["z"], facing=tele_data.get("facing", "FrontRight"))
                    await self.highrise.teleport(user.id, pos)
                    await self.highrise.send_whisper(user.id, t("teleported_to_location", tele_name))
                except Exception as e:
                    await self.highrise.send_whisper(user.id, t("teleport_error", str(e)))
                return

            await self.highrise.send_whisper(user.id, t("usage_teleport"))
            return

        # ---- !summ @user ----
        if cmd == "!summ":
            if not is_vip(user.username):
                await self.highrise.send_whisper(user.id, t("only_vip_and_above_teleport"))
                return
            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_summon"))
                return
            target_name = parts[1].lstrip("@")
            target_user, _ = await self._get_user_by_username(target_name)
            if not target_user:
                await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                return
            my_pos = await self._get_my_position(user.id)
            if not my_pos:
                await self.highrise.send_whisper(user.id, t("position_not_found"))
                return
            try:
                await self.highrise.teleport(target_user.id, my_pos)
                await self.highrise.send_whisper(user.id, t("user_summoned", target_name))
                await self.highrise.send_whisper(target_user.id, t("summoned_by_user", user.username))
            except Exception as e:
                await self.highrise.send_whisper(user.id, t("teleport_error", str(e)))
            return

        # ---- !bot x y z ----
        if cmd == "!bot":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_set_bot_position"))
                return
            if len(parts) < 4:
                settings = load_settings()
                bp = settings.get("bot_position")
                if bp:
                    await self.highrise.send_whisper(user.id, t("bot_position_set_success", bp["x"], bp["y"], bp["z"]))
                else:
                    await self.highrise.send_whisper(user.id, t("bot_position_error"))
                return
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                await self.highrise.send_whisper(user.id, t("invalid_coordinates"))
                return
            settings = load_settings()
            settings["bot_position"] = {"x": x, "y": y, "z": z, "facing": "FrontRight"}
            save_settings(settings)
            try:
                pos = Position(x, y, z, facing="FrontRight")
                await self.highrise.walk_to(pos)
                await self.highrise.send_whisper(user.id, t("bot_position_set_success", x, y, z))
            except Exception as e:
                await self.highrise.send_whisper(user.id, t("position_set_error", str(e)))
            return

        # ---- !emote ----
        if cmd == "!emote":
            if len(parts) >= 2 and parts[1].lower() == "list":
                await self._send_emote_list(user.id)
                return
            if len(parts) >= 2:
                query = parts[1]
                emote = find_emote(query)
                if emote:
                    self._start_emote_loop(user.id, emote)
                    await self.highrise.send_whisper(user.id, t("emote_loop_message", emote["name"]))
                else:
                    await self.highrise.send_whisper(user.id, t("emote_not_found", query))
                return
            await self.highrise.send_whisper(user.id, t("usage_emote"))
            return

        # ---- !lang ----
        if cmd == "!lang":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_can_change_language"))
                return
            if len(parts) < 2:
                langs_str = ", ".join(sorted(SUPPORTED_LANGS))
                await self.highrise.send_whisper(user.id, t("usage_language", langs_str))
                return
            lang_code = parts[1].lower()
            if lang_code not in SUPPORTED_LANGS:
                langs_str = ", ".join(sorted(SUPPORTED_LANGS))
                await self.highrise.send_whisper(user.id, t("invalid_language", langs_str))
                return
            settings = load_settings()
            settings["lang"] = lang_code
            save_settings(settings)
            lang_data = load_lang(lang_code)
            lang_name = lang_data.get("lang_name", lang_code)
            await self.highrise.send_whisper(user.id, t("language_changed", lang_name))
            return

        # ---- !welcome ----
        if cmd == "!welcome":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_can_change_welcome"))
                return
            if len(parts) < 2:
                settings = load_settings()
                current_msg = settings.get("welcome_message", "") or t("welcome_default")
                current_mode = settings.get("welcome_mode", "chat")
                await self.highrise.send_whisper(user.id, t("welcome_info", current_msg, current_mode))
                return
            sub = parts[1].lower()
            if sub == "whisper":
                settings = load_settings()
                settings["welcome_mode"] = "whisper"
                save_settings(settings)
                await self.highrise.send_whisper(user.id, t("welcome_now_whisper"))
                return
            if sub == "chat":
                settings = load_settings()
                settings["welcome_mode"] = "chat"
                save_settings(settings)
                await self.highrise.send_whisper(user.id, t("welcome_now_public"))
                return
            new_message = msg[len("!welcome "):]
            settings = load_settings()
            settings["welcome_message"] = new_message
            save_settings(settings)
            await self.highrise.send_whisper(user.id, t("welcome_message_updated", new_message))
            return

        # ---- !give ----
        if cmd == "!give":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_can_give_roles"))
                return
            if len(parts) < 3:
                await self.highrise.send_whisper(user.id, t("usage_give"))
                return
            target = parts[1].lstrip("@")
            role = parts[2].lower()
            valid_roles = {"host", "admin", "vip"}
            if role not in valid_roles:
                await self.highrise.send_whisper(user.id, t("valid_roles"))
                return
            roles = load_roles()
            if target not in roles:
                roles[target] = []
            if role in roles[target]:
                await self.highrise.send_whisper(user.id, t("user_already_has_role", target, role))
                return
            roles[target].append(role)
            save_roles(roles)
            await self.highrise.send_whisper(user.id, t("role_given_success", target, role))
            # Hedef kullanıcıya bildir
            target_user, _ = await self._get_user_by_username(target)
            if target_user:
                await self.highrise.send_whisper(target_user.id, t("role_received", role))
            return

        # ---- !remove ----
        if cmd == "!remove":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_can_remove_roles"))
                return
            if len(parts) < 3:
                await self.highrise.send_whisper(user.id, t("usage_remove"))
                return
            target = parts[1].lstrip("@")
            role = parts[2].lower()
            valid_roles = {"host", "admin", "vip"}
            if role not in valid_roles:
                await self.highrise.send_whisper(user.id, t("valid_roles"))
                return
            roles = load_roles()
            if target not in roles or role not in roles[target]:
                await self.highrise.send_whisper(user.id, t("user_doesnt_have_role", target, role))
                return
            roles[target].remove(role)
            if not roles[target]:
                del roles[target]
            save_roles(roles)
            await self.highrise.send_whisper(user.id, t("role_removed_success", role, target))
            target_user, _ = await self._get_user_by_username(target)
            if target_user:
                await self.highrise.send_whisper(target_user.id, t("role_lost", role))
            return

        # ---- !kick ----
        if cmd == "!kick":
            if not is_admin(user.username):
                await self.highrise.send_whisper(user.id, t("only_admins_can_moderate"))
                return
            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_kick"))
                return
            target_name = parts[1].lstrip("@")
            target_user, _ = await self._get_user_by_username(target_name)
            if not target_user:
                await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                return
            if target_user.id == self.bot_id:
                await self.highrise.send_whisper(user.id, t("cannot_kick_bot"))
                return
            if is_host(target_name):
                await self.highrise.send_whisper(user.id, t("cannot_kick_host"))
                return
            try:
                await self.highrise.moderate_room(target_user.id, "kick")
                await self.highrise.send_whisper(user.id, t("user_kicked", target_name, user.username))
            except Exception as e:
                await self.highrise.send_whisper(user.id, t("kick_error", str(e)))
            return

        # ---- !ban ----
        if cmd == "!ban":
            if not is_admin(user.username):
                await self.highrise.send_whisper(user.id, t("only_admins_can_moderate"))
                return
            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_ban"))
                return
            target_name = parts[1].lstrip("@")
            target_user, _ = await self._get_user_by_username(target_name)
            if not target_user:
                await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                return
            if target_user.id == self.bot_id:
                await self.highrise.send_whisper(user.id, t("cannot_ban_bot"))
                return
            if is_host(target_name):
                await self.highrise.send_whisper(user.id, t("cannot_kick_host"))
                return
            try:
                await self.highrise.moderate_room(target_user.id, "ban")
                if len(parts) >= 3:
                    duration_str = self._parse_duration_str(parts[2])
                    await self.highrise.send_whisper(user.id, t("user_banned_duration", target_name, duration_str, user.username))
                else:
                    await self.highrise.send_whisper(user.id, t("user_banned", target_name, user.username))
            except Exception as e:
                await self.highrise.send_whisper(user.id, t("ban_error", str(e)))
            return

        # ---- !unban ----
        if cmd == "!unban":
            if not is_admin(user.username):
                await self.highrise.send_whisper(user.id, t("only_admins_can_moderate"))
                return
            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_unban"))
                return
            target_name = parts[1].lstrip("@")
            try:
                await self.highrise.moderate_room(target_name, "unban")
                await self.highrise.send_whisper(user.id, t("user_unbanned", target_name, user.username))
            except Exception as e:
                await self.highrise.send_whisper(user.id, t("unban_error", str(e)))
            return

        # ---- !mute ----
        if cmd == "!mute":
            if not is_admin(user.username):
                await self.highrise.send_whisper(user.id, t("only_admins_can_moderate"))
                return
            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_mute"))
                return
            target_name = parts[1].lstrip("@")
            target_user, _ = await self._get_user_by_username(target_name)
            if not target_user:
                await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                return
            if target_user.id == self.bot_id:
                await self.highrise.send_whisper(user.id, t("cannot_mute_bot"))
                return
            if is_host(target_name):
                await self.highrise.send_whisper(user.id, t("cannot_mute_host"))
                return
            duration_seconds = None
            duration_str = ""
            if len(parts) >= 3:
                duration_seconds = self._parse_duration(parts[2])
                if duration_seconds is None:
                    await self.highrise.send_whisper(user.id, t("invalid_duration_format"))
                    return
                duration_str = self._parse_duration_str(parts[2])
            try:
                await self.highrise.moderate_room(target_user.id, "mute", duration_seconds)
                await self.highrise.send_whisper(user.id, t("user_muted", target_name, duration_str or "∞", user.username))
            except Exception as e:
                await self.highrise.send_whisper(user.id, t("mute_error", str(e)))
            return

        # ---- !unmute ----
        if cmd == "!unmute":
            if not is_admin(user.username):
                await self.highrise.send_whisper(user.id, t("only_admins_can_moderate"))
                return
            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_unmute"))
                return
            target_name = parts[1].lstrip("@")
            target_user, _ = await self._get_user_by_username(target_name)
            if not target_user:
                await self.highrise.send_whisper(user.id, t("user_not_found", target_name))
                return
            try:
                await self.highrise.moderate_room(target_user.id, "unmute")
                await self.highrise.send_whisper(user.id, t("user_unmuted", target_name, user.username))
            except Exception as e:
                await self.highrise.send_whisper(user.id, t("unmute_error", str(e)))
            return

        # ---- !loop ----
        if cmd == "!loop":
            if not is_host(user.username):
                await self.highrise.send_whisper(user.id, t("only_hosts_can_use_loop"))
                return
            if len(parts) < 2:
                await self.highrise.send_whisper(user.id, t("usage_loop"))
                return
            sub = parts[1].lower()
            if sub == "stop":
                if hasattr(self, '_loop_task') and self._loop_task:
                    self._loop_task.cancel()
                    self._loop_task = None
                    await self.highrise.send_whisper(user.id, t("loop_stopped"))
                return
            # Sayıysa interval ayarla
            try:
                seconds = int(parts[1])
                if seconds < 1:
                    await self.highrise.send_whisper(user.id, t("loop_interval_too_small"))
                    return
                settings = load_settings()
                settings["loop_interval"] = seconds
                save_settings(settings)
                await self.highrise.send_whisper(user.id, t("loop_interval_set", seconds))
                # Aktif loop varsa yeniden başlat
                if hasattr(self, '_loop_task') and self._loop_task:
                    self._loop_task.cancel()
                    self._loop_task = asyncio.create_task(self._chat_loop())
                    await self.highrise.send_whisper(user.id, t("loop_restarted_with_new_interval"))
                return
            except ValueError:
                pass
            # Mesaj olarak ayarla
            loop_msg = msg[len("!loop "):]
            settings = load_settings()
            settings["loop_message"] = loop_msg
            interval = settings.get("loop_interval", 30)
            save_settings(settings)
            if hasattr(self, '_loop_task') and self._loop_task:
                self._loop_task.cancel()
            self._loop_task = asyncio.create_task(self._chat_loop())
            await self.highrise.send_whisper(user.id, t("loop_message_set", interval, loop_msg))
            return

    async def _chat_loop(self):
        try:
            while True:
                settings = load_settings()
                msg = settings.get("loop_message", "")
                interval = settings.get("loop_interval", 30)
                if msg:
                    await self.highrise.chat(msg)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    def _parse_duration(self, text):
        text = text.lower().strip()
        try:
            if text.endswith("s"):
                return int(text[:-1])
            elif text.endswith("m"):
                return int(text[:-1]) * 60
            elif text.endswith("h"):
                return int(text[:-1]) * 3600
            elif text.endswith("d"):
                return int(text[:-1]) * 86400
        except ValueError:
            return None
        return None

    def _parse_duration_str(self, text):
        text = text.lower().strip()
        try:
            if text.endswith("s"):
                return t("duration_seconds", int(text[:-1]))
            elif text.endswith("m"):
                return t("duration_minutes", int(text[:-1]))
            elif text.endswith("h"):
                return t("duration_hours", int(text[:-1]))
            elif text.endswith("d"):
                return t("duration_days", int(text[:-1]))
        except ValueError:
            return text
        return text

    async def _send_emote_list(self, user_id):
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


if __name__ == "__main__":
    room_id = "67a8a35c3c5e0a796e05dfef"
    api_key = "7394308cbc3189d365774c71c74758068269f7d00164c05edd6662644518fef2"

    import sys
    sys.argv = ["main", "bot:Bot", room_id, api_key]
    __main__.main()
