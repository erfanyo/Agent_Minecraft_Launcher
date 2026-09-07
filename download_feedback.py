"""Player-facing suggestions, kept separate from technical error details."""
def failure_advice(error):
    low = str(error).lower()
    if any(s in low for s in ('403', '401', 'forbidden', 'unauthorized')):
        return "下载站没放行。换个下载源试试？如果是 CurseForge，检查一下自己的 API Key。"
    if '404' in low:
        return "这个文件好像不在原来的地址了。换个版本，或者换个下载源试试？"
    if '429' in low:
        return "下载站说咱们请求太快了，歇一会儿再试吧。"
    if any(s in low for s in ('space', '磁盘', 'errno 28', 'winerror 112')):
        return "磁盘可能装不下了，腾点空间再试试？"
    if any(s in low for s in ('permission', '拒绝访问', 'winerror 5')):
        return "文件好像被占用或不让写。关掉游戏，检查一下文件夹权限再试试？"
    if any(s in low for s in ('timeout', 'connection', 'ssl', 'resolve', '网络', '超时')):
        return "网络好像没连稳。连热点试试？也可以到设置里换个下载源。"
    if any(s in low for s in ('sha1', '校验')):
        return "文件没下完整，或者校验没过。重新下载试试？一直不行就换个源。"
    return "这次没装好，点下载球看看具体原因吧。网络相关的话，连热点试试？"
