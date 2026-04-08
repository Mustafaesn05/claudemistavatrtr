import json
import os
from highrise import BaseBot, __main__
from highrise.models import User

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
ROLES_FILE = os.path.join(DATA_DIR, "roles.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
LANGS_DIR = os.path.join(DATA_DIR, "langs")

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
        "lang": "tr"
    })


def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


def load_lang(lang_code):
    path = os.path.join(LANGS_DIR, f"{lang_code}.json")
    return load_json(path, {})


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


class Bot(BaseBot):
    async def on_start(self, session_metadata):
        print("Bot odaya katıldı!")

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

    async def on_chat(self, user, message):
        msg = message.strip()

        if not msg.startswith("!"):
            return

        parts = msg.split(None, 2)
        cmd = parts[0].lower()

        # --- !lang komutu (sadece host) ---
        if cmd == "!lang":
            if not is_host(user.username):
                await self.highrise.chat(t("host_only"))
                return

            if len(parts) < 2:
                await self.highrise.chat(t("lang_usage"))
                return

            lang_code = parts[1].lower()
            if lang_code not in SUPPORTED_LANGS:
                await self.highrise.chat(t("lang_invalid"))
                return

            settings = load_settings()
            settings["lang"] = lang_code
            # Hoş geldin mesajını sıfırla (yeni dilin default'u kullanılsın)
            settings["welcome_message"] = ""
            save_settings(settings)
            # Yeni dilde onay mesajı
            await self.highrise.chat(t("lang_changed"))
            return

        # --- !welcome komutu (sadece host) ---
        if cmd == "!welcome":
            if not is_host(user.username):
                await self.highrise.chat(t("host_only"))
                return

            if len(parts) < 2:
                settings = load_settings()
                current_msg = settings.get("welcome_message", "")
                if not current_msg:
                    current_msg = t("welcome_default")
                current_mode = settings.get("welcome_mode", "chat")
                await self.highrise.chat(t("welcome_info", message=current_msg, mode=current_mode))
                return

            sub = parts[1].lower()

            if sub == "whisper":
                settings = load_settings()
                settings["welcome_mode"] = "whisper"
                save_settings(settings)
                await self.highrise.chat(t("welcome_mode_whisper"))
                return

            if sub == "chat":
                settings = load_settings()
                settings["welcome_mode"] = "chat"
                save_settings(settings)
                await self.highrise.chat(t("welcome_mode_chat"))
                return

            # !welcome <mesaj>
            new_message = msg[len("!welcome "):]
            settings = load_settings()
            settings["welcome_message"] = new_message
            save_settings(settings)
            await self.highrise.chat(t("welcome_updated", message=new_message))
            return

        # --- !give komutu (sadece host) ---
        if cmd == "!give":
            if not is_host(user.username):
                await self.highrise.chat(t("host_only"))
                return

            if len(parts) < 3:
                await self.highrise.chat(t("give_usage"))
                return

            target = parts[1].lstrip("@")
            role_list = [r.strip().lower() for r in parts[2].split(",")]
            valid_roles = {"host", "admin", "vip"}
            invalid = [r for r in role_list if r not in valid_roles]
            if invalid:
                await self.highrise.chat(t("invalid_roles", roles=", ".join(invalid)))
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
                await self.highrise.chat(t("roles_added", target=target, roles=", ".join(added)))
            else:
                await self.highrise.chat(t("roles_already", target=target))
            return

        # --- !remove komutu (sadece host) ---
        if cmd == "!remove":
            if not is_host(user.username):
                await self.highrise.chat(t("host_only"))
                return

            if len(parts) < 3:
                await self.highrise.chat(t("remove_usage"))
                return

            target = parts[1].lstrip("@")
            role_list = [r.strip().lower() for r in parts[2].split(",")]
            valid_roles = {"host", "admin", "vip"}
            invalid = [r for r in role_list if r not in valid_roles]
            if invalid:
                await self.highrise.chat(t("invalid_roles", roles=", ".join(invalid)))
                return

            roles = load_roles()
            if target not in roles:
                await self.highrise.chat(t("no_roles", target=target))
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
                await self.highrise.chat(t("roles_removed", target=target, roles=", ".join(removed)))
            else:
                await self.highrise.chat(t("roles_not_have", target=target))
            return

    async def on_user_leave(self, user):
        print(f"{user.username} odadan ayrıldı.")


if __name__ == "__main__":
    room_id = "67a8a35c3c5e0a796e05dfef"
    api_key = "7394308cbc3189d365774c71c74758068269f7d00164c05edd6662644518fef2"

    import sys
    sys.argv = ["main", "bot:Bot", room_id, api_key]
    __main__.main()
