# -*- coding: utf-8 -*-
"""本地模型基准 runner:起模型 → 跑单步用例 → 记速度/资源 → 出结果。

用法:
  python runner.py --model qwen3.5-0.8b          # 跑单个模型
  python runner.py --all                          # 按 config.run_order 全跑
  python runner.py --model X --runs 3             # 每用例跑 3 次平均(测速)
  python runner.py --model X --sets single        # 只跑单步(默认)

结果写 benchmark/results/<model>.json,report.py 再汇总成 md。

设计:每次只起一个模型(单模型顺序跑),记录 tok/s、TTFT、加载时间、显存/内存。
llama.cpp 起 OpenAI 兼容服务(/v1/chat/completions),用纯 HTTP(零重依赖)。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_BENCH = os.path.dirname(os.path.abspath(__file__))
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

import judge
from testset import single as single_set


# ---------- 配置 ----------
def load_config(path=None):
    """读 config.json(零依赖,与项目其它配置一致)。相对路径相对 benchmark/ 解析。"""
    path = path or os.path.join(_BENCH, "config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_bench"] = _BENCH
    tgd = cfg.get("test_game_dir")
    if tgd and not os.path.isabs(tgd):
        cfg["test_game_dir"] = os.path.normpath(os.path.join(_BENCH, tgd))
    return cfg


def model_by_id(cfg, mid):
    for m in cfg.get("models", []):
        if m.get("id") == mid:
            return m
    raise KeyError(f"config 里没有模型:{mid}")


# ---------- 模型服务(llama.cpp) ----------
class LlamaServer:
    """起 llama-server,等 /health,测完关。记录加载时间和 PID(算资源)。"""

    def __init__(self, cfg, model, gpu=None):
        self.cfg = cfg
        self.model = model
        self.gpu = gpu
        self.proc = None
        self.port = self._pick_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.load_seconds = 0.0

    def _pick_port(self):
        if self.model.get("backend") == "script":
            return int(self.model.get("port", 8090))
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    def start(self):
        backend = self.model.get("backend", "llama.cpp")
        if backend == "script":
            return self._start_script()
        return self._start_llama_cpp()

    def _start_script(self):
        """Bonsai 等:用现成脚本起(脚本自己定端口/参数)。"""
        script = self.model["script"]
        workdir = os.path.dirname(os.path.join(self.cfg["_bench"], "..", script))
        self.proc = subprocess.Popen(
            ["cmd", "/c", script], cwd=workdir,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self._wait_health()

    def _start_llama_cpp(self):
        lc = self.cfg.get("llama_cpp", {})
        server = lc.get("server")
        gguf = os.path.join(self.cfg["models_dir"], self.model["gguf"])
        if not os.path.isfile(gguf):
            raise FileNotFoundError(f"GGUF 不存在:{gguf}")
        cmd = [server, "-m", gguf, "--host", "127.0.0.1", "--port", str(self.port),
               "-c", str(lc.get("ctx", 8192)), "--no-webui", "-np", "1"]
        ngl = lc.get("ngl", 99) if self.gpu != "cpu" else 0
        cmd += ["-ngl", str(ngl)]
        if lc.get("threads"):
            cmd += ["-t", str(lc["threads"])]
        cmd += lc.get("extra_args", [])
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return self._wait_health()

    def _wait_health(self, wait=120):
        t0 = time.monotonic()
        for _ in range(wait * 2):
            try:
                if urllib.request.urlopen(f"{self.base}/health", timeout=2).status == 200:
                    self.load_seconds = time.monotonic() - t0
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"模型启动超时:{self.model.get('id')}")

    def chat(self, messages, temperature=0.0, max_tokens=1024):
        """调 /v1/chat/completions,返回 (content, usage, elapsed)。
        关闭 thinking(Qwen3.5 默认开思考,会把 token 全花在 reasoning_content,content 空);
        若仍进了 reasoning_content,兜底从那里抠。"""
        body = json.dumps({
            "model": self.model.get("id", "local"),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "thinking": {"type": "disabled"},
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read())
        elapsed = time.monotonic() - t0
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        if not content.strip():
            # 兜底:模型把答案写进了 reasoning_content(Qwen thinking 模式)
            content = msg.get("reasoning_content") or ""
        usage = data.get("usage") or {}
        return content, usage, elapsed

    def stop(self):
        """杀掉整棵进程树(含 .bat 拉起的孙子 llama-server),不留残留。"""
        if self.proc and self.proc.poll() is None:
            pid = self.proc.pid
            if os.name == "nt":
                # taskkill /T 杀进程树(cmd.exe → llama-server.exe 一起杀)
                try:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            else:
                try:
                    os.killpg(os.getpgid(pid), 15)
                except Exception:
                    self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None


# ---------- 从模型输出提取工具调用 ----------
def extract_tool_call(text: str):
    """从模型文本里抠 {name, arguments}(容错:模型可能啰嗦/加代码块/带嵌套 {})。"""
    if not text:
        return "", {}
    t = text.strip()
    # 1) 整段就是 JSON
    try:
        obj = json.loads(t)
        if isinstance(obj, dict) and "name" in obj:
            return obj.get("name", ""), obj.get("arguments") or {}
    except Exception:
        pass
    # 2) 从每个 '{' 尝试 raw_decode(容错嵌套/代码块/前后啰嗦)
    dec = json.JSONDecoder()
    idx = 0
    while True:
        i = t.find("{", idx)
        if i < 0:
            break
        try:
            obj, _end = dec.raw_decode(t[i:])
            if isinstance(obj, dict) and "name" in obj:
                return obj.get("name", ""), obj.get("arguments") or {}
        except Exception:
            pass
        idx = i + 1
    return "", {}


# ---------- 跑单步用例 ----------
def _build_system_prompt():
    """构造评测用 system:列工具名 + 强约束输出格式(0.8B 必须明确约束才不瞎填)。"""
    import launcher_app.ai.assistant as assistant
    from launcher_app.ai.ai_testset import SYSTEM_TEMPLATE, DEFAULT_INSTANCES
    names = [t["function"]["name"] for t in assistant.TOOLS]
    tool_list = ", ".join(sorted(names))
    base = SYSTEM_TEMPLATE.format(instances=DEFAULT_INSTANCES)
    return (
        base +
        f" 可用服务端:{single_set.DEFAULT_SERVERS}。"
        f"\n\n【可用工具名】(name 必须从中选一个):{tool_list}"
        "\n【输出格式】只输出一行 JSON,格式严格为:"
        '\n{"name": "<工具名>", "arguments": {<参数>}}'
        "\n不要解释、不要 markdown 代码块、不要多余文字。"
        "\n【示例】"
        '\n用户:看看我有哪些实例'
        '\n你:{"name": "list_instances", "arguments": {}}'
        '\n用户:neoforge-21.1.248 装了哪些mod'
        '\n你:{"name": "list_mods", "arguments": {"instance": "neoforge-21.1.248"}}'
        "\n现在按此格式回答。"
    )


def run_single(server, cfg, cases, runs=1, system_extra=""):
    """跑单步用例,返回 (results, speed)。runs>1 每条跑多次(取速度平均,评分取最佳)。"""
    sys_prompt = _build_system_prompt() + system_extra
    results = []
    elapsed_all, tok_all = [], []
    for case in cases:
        best = None
        for _ in range(max(1, runs)):
            msgs = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": case["user"]},
            ]
            content, usage, elapsed = server.chat(msgs, temperature=0.0, max_tokens=256)
            name, args = extract_tool_call(content)
            comp_tok = int(usage.get("completion_tokens") or 0)
            if comp_tok > 0 and elapsed > 0:
                elapsed_all.append(elapsed)
                tok_all.append(comp_tok / elapsed)
            r = judge.score_case(case, name, args)
            if best is None or (r["name_ok"], r["args_score"]) > (best["name_ok"], best["args_score"]):
                best = r
        results.append(best)
    speed = {
        "avg_tok_per_s": (sum(tok_all) / len(tok_all)) if tok_all else 0.0,
        "avg_latency_s": (sum(elapsed_all) / len(elapsed_all)) if elapsed_all else 0.0,
    }
    return results, speed


# ---------- 多步剧本(纯剧本:预设工具回复,观察决策链) ----------
def run_multistep(server, cfg, scripts):
    """跑多步剧本:发起请求→模型调工具→喂预设回复→看下一步→…产出决策链(供人工面试)。
    返回 {script_id: {"user", "chain":[{step, tool, args, tool_reply}], "auto_hint"}}。"""
    from launcher_app.ai.ai_testset import SYSTEM_TEMPLATE, DEFAULT_INSTANCES
    base_sys = SYSTEM_TEMPLATE.format(instances=DEFAULT_INSTANCES) + \
        f" 可用服务端:{single_set.DEFAULT_SERVERS}。\n" + _tool_format_block()
    out = {}
    for sc in scripts:
        msgs = [{"role": "system", "content": base_sys},
                {"role": "user", "content": sc["user"]}]
        chain = []
        for si, step in enumerate(sc["steps"]):
            # 让模型做第 si 步决策
            content, _usage, _el = server.chat(msgs, temperature=0.0, max_tokens=256)
            name, args = extract_tool_call(content)
            tool_reply = step.get("tool_reply", "")
            # 该步的期望工具集(判断方向对不对)
            expected = set(step.get("expect_tool", []))
            direction_ok = (name in expected) if expected else None
            chain.append({
                "step": si + 1,
                "tool": name,
                "args": args,
                "tool_reply": tool_reply,
                "expected_any": sorted(expected),
                "direction_ok": direction_ok,
                "raw": content[:200],
            })
            # 把"工具回复"喂回给模型,继续下一步
            if tool_reply:
                msgs.append({"role": "assistant", "content": content or f"[调用 {name}]"})
                msgs.append({"role": "user", "content": f"工具「{name}」返回:\n{tool_reply}\n接下来怎么做?"})
        # 自动初评:方向命中比例(人工面试再定 A/B/C/D)
        ok_steps = sum(1 for c in chain if c["direction_ok"])
        out[sc["id"]] = {
            "user": sc["user"],
            "note": sc.get("note", ""),
            "expect_final": sc.get("expect_final", ""),
            "chain": chain,
            "direction_hit": ok_steps / len(chain) if chain else 0.0,
            "auto_hint": f"方向命中 {ok_steps}/{len(chain)} 步",
        }
    return out


def _tool_format_block():
    """多步用的输出格式约束(同 single)。"""
    import launcher_app.ai.assistant as assistant
    from launcher_app.ai.ai_testset import SYSTEM_TEMPLATE  # noqa
    names = ", ".join(sorted(t["function"]["name"] for t in assistant.TOOLS))
    return (f"【可用工具名】(name 必须从中选):{names}\n"
            "【输出格式】只输出 JSON:{\"name\": \"<工具名>\", \"arguments\": {<参数>}}\n"
            "不要解释、不要 markdown。多步任务里每步只调一个工具。")


# ---------- 主流程 ----------
def run_model(cfg, mid, runs=1, gpu=None, sets=("single",)):
    model = model_by_id(cfg, mid)
    print(f"\n=== {model.get('name', mid)} ({model.get('quant','?')}) ===")
    server = LlamaServer(cfg, model, gpu=gpu)
    server.start()
    print(f"  加载 {server.load_seconds:.1f}s | 端口 {server.port}")
    out = {"model": model, "load_seconds": round(server.load_seconds, 2),
           "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        if "single" in sets:
            results, speed = run_single(server, cfg, single_set.CASES, runs=runs)
            out["summary"] = judge.summarize(results)
            out["speed"] = speed
            out["results"] = results
            print(f"  [single] 工具名 {out['summary']['name_acc']:.1%} | 参数 {out['summary']['args_avg']:.1%} "
                  f"| 瞎编 {out['summary']['halluc_rate']:.1%} | {speed['avg_tok_per_s']:.1f} tok/s")
        if "fuzzy" in sets:
            from testset import fuzzy as fuzzy_set
            fz_results, _ = run_single(server, cfg, fuzzy_set.CASES, runs=1)
            out["fuzzy_summary"] = judge.summarize(fz_results)
            out["fuzzy_results"] = fz_results
            print(f"  [fuzzy] 合理路径命中 {out['fuzzy_summary']['name_acc']:.1%}")
        if "multistep" in sets:
            from testset import multistep as ms_set
            ms = run_multistep(server, cfg, ms_set.CASES)
            out["multistep"] = ms
            avg_dir = sum(m["direction_hit"] for m in ms.values()) / len(ms) if ms else 0
            print(f"  [multistep] 方向命中均值 {avg_dir:.1%}(详见 results/<id>.json)")
    finally:
        server.stop()
    res_dir = os.path.join(_BENCH, "results")
    os.makedirs(res_dir, exist_ok=True)
    with open(os.path.join(res_dir, f"{mid}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--model", default=None, help="模型 id(见 config.json)")
    ap.add_argument("--all", action="store_true", help="按 run_order 全跑")
    ap.add_argument("--runs", type=int, default=1, help="每用例跑几次(测速平均)")
    ap.add_argument("--gpu", choices=["auto", "cpu", "vulkan"], default=None)
    ap.add_argument("--sets", default="single",
                    help="跑哪些测试集(逗号分隔):single,fuzzy,multistep")
    args = ap.parse_args()

    sets = tuple(s.strip() for s in args.sets.split(",") if s.strip())
    cfg = load_config(args.config)
    if args.all:
        mids = cfg.get("run_order", [])
    elif args.model:
        mids = [args.model]
    else:
        print("指定 --model <id> 或 --all"); return 2
    for mid in mids:
        try:
            run_model(cfg, mid, runs=args.runs, gpu=args.gpu, sets=sets)
        except Exception as e:
            print(f"  [跳过] {mid}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
