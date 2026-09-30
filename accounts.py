"""Account lists with legacy active-account fields kept for the launch path."""


def offline_names(settings: dict) -> list[str]:
    names = []
    seen = set()
    for value in [settings.get("username", "Steve"), *(settings.get("offline_accounts") or [])]:
        name = str(value or "").strip()
        if name and name.casefold() not in seen:
            names.append(name)
            seen.add(name.casefold())
    return names


def microsoft_accounts(settings: dict) -> list[dict]:
    accounts = []
    positions = {}
    for value in settings.get("microsoft_accounts") or []:
        if not isinstance(value, dict) or not value.get("uuid"):
            continue
        identity = str(value["uuid"]).replace("-", "").lower()
        if identity not in positions:
            positions[identity] = len(accounts)
            accounts.append(dict(value))
    current = settings.get("ms_credentials") or {}
    if isinstance(current, dict) and current.get("uuid"):
        identity = str(current["uuid"]).replace("-", "").lower()
        if identity in positions:
            accounts[positions[identity]].update(current)
        else:
            accounts.append(dict(current))
    return accounts


def save_microsoft_login(result: dict) -> dict:
    from settings import update_settings
    credential = {key: result.get(key, "") for key in
                  ("username", "uuid", "access_token", "refresh_token")}
    if not credential["uuid"]:
        raise ValueError("微软登录未返回玩家 UUID")

    def change(settings):
        accounts = microsoft_accounts(settings)
        identity = credential["uuid"].replace("-", "").lower()
        accounts = [item for item in accounts
                    if str(item.get("uuid", "")).replace("-", "").lower() != identity]
        accounts.append(credential)
        settings["microsoft_accounts"] = accounts
        settings["ms_credentials"] = credential
        settings["login_method"] = "microsoft"

    return update_settings(change)


def select_microsoft(uuid: str) -> dict:
    from settings import update_settings
    identity = str(uuid).replace("-", "").lower()

    def change(settings):
        account = next((item for item in microsoft_accounts(settings)
                        if str(item["uuid"]).replace("-", "").lower() == identity), None)
        if account is None:
            raise ValueError("找不到这个正版账号")
        settings["microsoft_accounts"] = microsoft_accounts(settings)
        settings["ms_credentials"] = dict(account)
        settings["login_method"] = "microsoft"

    return update_settings(change)


def remove_microsoft(uuid: str) -> dict:
    from settings import update_settings
    identity = str(uuid).replace("-", "").lower()

    def change(settings):
        accounts = [item for item in microsoft_accounts(settings)
                    if str(item["uuid"]).replace("-", "").lower() != identity]
        settings["microsoft_accounts"] = accounts
        active = (settings.get("ms_credentials") or {}).get("uuid", "")
        if active.replace("-", "").lower() == identity:
            settings["ms_credentials"] = dict(accounts[0]) if accounts else {}
            if not accounts:
                settings["login_method"] = "offline"

    return update_settings(change)


def select_offline(name: str) -> dict:
    from settings import update_settings
    name = str(name).strip()
    if not name:
        raise ValueError("离线昵称不能为空")

    def change(settings):
        names = offline_names(settings)
        if name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
        settings["offline_accounts"] = names
        settings["username"] = name
        settings["login_method"] = "offline"

    return update_settings(change)


def remove_offline(name: str) -> dict:
    from settings import update_settings

    def change(settings):
        names = [item for item in offline_names(settings)
                 if item.casefold() != str(name).casefold()]
        if not names:
            names = ["Steve"]
        settings["offline_accounts"] = names
        if str(settings.get("username", "")).casefold() == str(name).casefold():
            settings["username"] = names[0]

    return update_settings(change)


def update_refreshed_microsoft_credentials(uuid: str, credential: dict) -> dict:
    """Persist a refresh for its own UUID, even if the user switched accounts meanwhile."""
    from settings import update_settings
    identity = str(uuid).replace("-", "").lower()

    def change(settings):
        accounts = microsoft_accounts(settings)
        for item in accounts:
            if str(item["uuid"]).replace("-", "").lower() == identity:
                item.update(credential)
                break
        else:
            return  # 账号已在启动准备期间被移除，不重新添加凭证
        settings["microsoft_accounts"] = accounts
        active = settings.get("ms_credentials") or {}
        if str(active.get("uuid", "")).replace("-", "").lower() == identity:
            settings["ms_credentials"] = dict(credential)

    return update_settings(change)
