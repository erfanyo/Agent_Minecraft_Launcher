"""Shared API model catalog and explicit selection, independent of Qt."""


def api_models(settings):
    items = []
    profiles = settings.get('ai_model_providers') or {}
    for pid, profile in profiles.items():
        label = profile.get('name') or ('自定义' if pid.startswith('custom') else pid)
        for model in profile.get('models') or []:
            mid = str(model.get('id') or '').strip()
            if mid:
                items.append((f'cloud:{pid}:{mid}', f"{label} · {model.get('name') or mid}"))
    pid = settings.get('ai_cloud_provider') or 'cloud'
    mid = settings.get('ai_cloud_model') or ''
    key = f'cloud:{pid}:{mid}'
    if mid and not any(i[0] == key for i in items):
        items.append((key, f'{pid} · {mid}'))
    return items


def activate_api(settings, pid, model):
    profile = (settings.get('ai_model_providers') or {}).get(pid)
    if profile is not None:
        base, key = profile.get('base_url', ''), profile.get('api_key', '')
    elif pid == settings.get('ai_cloud_provider'):
        base, key = settings.get('ai_cloud_base_url', ''), settings.get('ai_cloud_api_key', '')
    else:
        raise ValueError('模型来源已删除，请重新选择。')
    settings.update(ai_source='cloud', ai_strategy='cloud_first',
                    ai_cloud_provider=pid, ai_cloud_model=model,
                    ai_cloud_base_url=base, ai_cloud_api_key=key,
                    ai_provider=pid, ai_model=model, ai_base_url=base, ai_api_key=key,
                    ai_configured=bool(base and model))
