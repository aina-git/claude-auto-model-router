#!/usr/bin/env python3
"""Auto Model Router for Claude Code (Haiku 5.5 -> Sonnet 5.5 -> Opus 5.5 -> Fable 5.2). Fails open."""
from __future__ import annotations
import glob, json, os, re, sys, time
from pathlib import Path

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
DATA_DIR = Path(os.environ.get("AMR_DATA_DIR") or CLAUDE_HOME / "auto-model-router")
TIERS = ["haiku", "sonnet", "opus", "fable"]

def _deep_merge(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base

def load_config() -> dict:
    cfg = json.loads((PLUGIN_ROOT / "config" / "router.json").read_text())
    override = CLAUDE_HOME / "auto-model-router" / "router.json"
    if override.is_file():
        try:
            _deep_merge(cfg, json.loads(override.read_text()))
        except Exception:
            pass
    return cfg

def load_state() -> dict:
    try:
        return json.loads((DATA_DIR / "state.json").read_text())
    except Exception:
        return {}

def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sessions = state.get("sessions", {})
    if len(sessions) > 200:
        state["sessions"] = dict(sorted(sessions.items(), key=lambda kv: kv[1].get("ts", 0))[-100:])
    tmp = DATA_DIR / "state.json.tmp"
    tmp.write_text(json.dumps(state))
    tmp.replace(DATA_DIR / "state.json")

def log_decision(rec: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "decisions.jsonl", "a") as fh:
        fh.write(json.dumps(rec) + "\n")

def tier_of_model(model: str | None) -> str | None:
    m = (model or "").lower()
    for t in ("haiku", "sonnet", "opus"):
        if t in m:
            return t
    return "fable" if ("fable" in m or "mythos" in m) else None

SIGNALS: list[tuple[str, int, str]] = [
    (r"\b(typo|spelling|grammar|rename|reformat|format(ting)?|lint|prettier|indent)\b", -10, "mechanical edit"),
    (r"\b(what is|what's|who is|define|meaning of|how do i|how to)\b", -6, "simple question"),
    (r"\b(list|show|print|count|find|locate|where is|search for|grep|look up)\b", -6, "lookup"),
    (r"\b(git (status|log|diff|add|commit|push|pull|checkout|branch)|commit message|changelog|bump (the )?version)\b", -10, "git chore"),
    (r"\b(summari[sz]e|tl;?dr|translate|convert|extract|classify|tag|sort)\b", -6, "transform"),
    (r"\b(add (a )?comment|docstring|readme|rename variable|update (the )?import)\b", -6, "small doc/edit"),
    (r"\b(run (the )?(tests?|build|script|linter)|install|npm i|pip install)\b", -5, "run command"),
    (r"\b(implement|build|create|write|add) (a |an |the )?(function|feature|endpoint|component|script|class|test|page|form|api|cli|hook|query)\b", 16, "implement feature"),
    (r"\b(add|implement|build|create|support|enable)\b.{0,40}\b(toggle|feature|button|page|screen|endpoint|route|mode|option|setting|validation|logging|caching|cache|pagination|search|filter|upload|login|signup|notification|webhook|integration)s?\b", 14, "add functionality"),
    (r"\b(fix|debug|resolve)\b.*\b(bug|error|exception|issue|failing|crash|traceback)\b", 16, "bug fix"),
    (r"\b(unit tests?|integration tests?|test coverage|write tests)\b", 12, "tests"),
    (r"\b(refactor|clean ?up|restructure|simplify)\b", 16, "refactor"),
    (r"\b(explain (why|how)|walk me through|compare|pros and cons|trade-?offs?)\b", 10, "reasoned explanation"),
    (r"\b(regex|sql|dockerfile|ci|github actions|yaml|schema)\b", 6, "technical artefact"),
    (r"\b(across|multiple|several|all|many) (files|modules|services|packages|repos|components)\b", 22, "multi-file scope"),
    (r"\b(migrat(e|ion)|upgrade (to|from)|port (to|from)|rewrite)\b", 20, "migration/rewrite"),
    (r"\b(performance|optimi[sz]e|latency|throughput|memory leak|profil(e|ing)|bottleneck)\b", 24, "performance"),
    (r"\b(race condition|deadlock|concurren(cy|t)|thread[- ]safe|async bug|flaky|heisenbug|intermittent)\b", 24, "concurrency/flaky"),
    (r"\b(security|vulnerab|exploit|auth(entication|orization)?|oauth|encryption|cve|threat model)\b", 18, "security"),
    (r"\b(root cause|post-?mortem|investigate|diagnose|why does .* (fail|break|hang))\b", 16, "root cause"),
    (r"\b(code review|review (this|the|my) (pr|pull request|code|diff)|audit)\b", 14, "review/audit"),
    (r"\b(design (an |the )?(api|schema|data model|database)|state machine|algorithm|data structure)\b", 18, "design"),
    (r"\b(architect(ure)?|system design|design (the|a) (whole|entire|new) system|distributed system)\b", 34, "architecture"),
    (r"\b(from scratch|greenfield|end[- ]to[- ]end|full[- ]stack app|entire (codebase|repo|project|application)|monorepo)\b", 26, "large scope"),
    (r"\b(long[- ]running|autonomous(ly)?|multi[- ]day|overnight|for hours|orchestrat(e|ion) (agents|subagents))\b", 26, "long-horizon"),
    (r"\b(prove|proof|formal(ly)? verif|theorem|novel (algorithm|approach)|research (paper|problem)|state of the art)\b", 28, "research/proof"),
    (r"\b(compiler|operating system|kernel|database engine|consensus (algorithm|protocol)|cryptograph)\b", 24, "systems-level"),
    (r"\b(strategy|roadmap|business plan|due diligence|legal analysis|financial model)\b", 14, "strategic analysis"),
    (r"\b(production|prod\b|live (site|system|data)|customer data|hipaa|pci|gdpr|payments?|billing)\b", 10, "high stakes"),
    (r"\b(think (hard|harder|deeply|carefully)|ultrathink|be thorough|deep dive|in depth|step by step)\b", 15, "depth requested"),
]
COMPILED = [(re.compile(p, re.I), w, label) for p, w, label in SIGNALS]
FORCE_RE = re.compile(r"(?:^|\s)[@#](haiku|sonnet|opus|fable)\b", re.I)
CONTINUE_RE = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|yes|yep|yeah|sure|go(?: ahead| on)?|continue|proceed|do it|next|keep going|sounds good|"
    r"looks good|lgtm|great|thanks?(?: you)?|thx|perfect|nice|cool|please|y|1|2|3|a|b|c)[\s,.!]*)+$", re.I
)
RETRY_RE = re.compile(
    r"\b(still (not|doesn'?t|broken|failing|wrong)|didn'?t (work|fix)|same (error|issue|problem)|"
    r"wrong again|not working|doesn'?t work|try (again|harder)|that'?s wrong|you broke)\b", re.I
)
PATH_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.\w{1,6}|\b[\w-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|cs|cpp|c|h|swift|sql|md|json|ya?ml|toml)\b")
STEP_RE = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S")
CHAIN_RE = re.compile(r"\b(and then|after that|afterwards|finally|also|additionally|as well as)\b", re.I)
MODEL_RE = re.compile(rb'"model":"(claude-[a-z0-9.\-]+)"')

def score_prompt(prompt: str) -> dict:
    text = prompt or ""
    words = len(text.split())
    score, reasons, seen = 20, [], {}
    for rx, w, label in COMPILED:
        if rx.search(text) and label not in seen:
            seen[label] = w
    pos = sorted((w for w in seen.values() if w > 0), reverse=True)
    neg = [w for w in seen.values() if w < 0]
    pos_total = sum(w * (0.6 ** i) for i, w in enumerate(pos))
    score += pos_total + (sum(neg) if pos_total < 20 else sum(neg) / 3)
    reasons += [f"{l} ({w:+d})" for l, w in sorted(seen.items(), key=lambda kv: -abs(kv[1]))]
    if words <= 8: score -= 6; reasons.append("very short (-6)")
    elif words > 1200: score += 18; reasons.append("very long (+18)")
    elif words > 400: score += 10; reasons.append("long (+10)")
    elif words > 150: score += 4; reasons.append("medium (+4)")
    cb = text.count("```") // 2
    if cb: add = min(12, 4 * cb); score += add; reasons.append(f"{cb} code block(s) (+{add})")
    paths = len(set(PATH_RE.findall(text)))
    if paths >= 2: add = min(15, 3 * paths); score += add; reasons.append(f"{paths} files (+{add})")
    steps = len(STEP_RE.findall(text))
    if steps >= 3: add = min(15, 2 * steps); score += add; reasons.append(f"{steps} steps (+{add})")
    chains = len(CHAIN_RE.findall(text))
    if chains >= 2: add = min(10, 3 * chains); score += add; reasons.append(f"chained (+{add})")
    return {"score": max(0, min(100, round(score))), "reasons": reasons[:6], "words": words}

def tier_for_score(score: int, cfg: dict, mode: str) -> str:
    sh = cfg.get("mode_shift", {}).get(mode, 0)
    th = cfg["thresholds"]
    if score >= th["fable"] + sh: return "fable"
    if score >= th["opus"] + sh: return "opus"
    if score >= th["sonnet"] + sh: return "sonnet"
    return "haiku"

def cap(tier: str, cfg: dict) -> str:
    mx = cfg.get("max_tier", "fable")
    return TIERS[min(TIERS.index(tier), TIERS.index(mx))] if mx in TIERS else tier

def route(prompt: str, cfg: dict, mode: str, session: dict | None) -> dict:
    session = session or {}
    last = session.get("last_tier")
    fresh = last and (time.time() - session.get("ts", 0) < cfg.get("sticky_minutes", 30) * 60)
    m = FORCE_RE.search(prompt or "")
    if m:
        t = m.group(1).lower()
        return {"tier": t, "score": None, "reasons": [f"forced @{t}"], "why": "override"}
    if fresh and CONTINUE_RE.match(prompt or ""):
        return {"tier": last, "score": None, "reasons": ["sticky continuation"], "why": "sticky"}
    s = score_prompt(prompt)
    tier, why = tier_for_score(s["score"], cfg, mode), "score"
    if fresh and RETRY_RE.search(prompt or ""):
        bumped = TIERS[min(3, TIERS.index(last) + 1)]
        if TIERS.index(bumped) > TIERS.index(tier):
            tier, why = bumped, "escalated"
            s["reasons"].insert(0, f"retry after {last} -> escalate")
    return {"tier": cap(tier, cfg), "score": s["score"], "reasons": s["reasons"], "why": why}

def current_session_model(transcript_path: str | None, session: dict, cfg: dict) -> str:
    if transcript_path and os.path.isfile(transcript_path):
        try:
            with open(transcript_path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 256_000))
                found = MODEL_RE.findall(fh.read())
            if found:
                return found[-1].decode()
        except Exception:
            pass
    return session.get("model") or cfg.get("assumed_session_model", "claude-haiku-5-5")

def build_directive(decision: dict, session_tier: str, cfg: dict) -> str | None:
    tier = decision["tier"]
    info = cfg["tiers"][tier]
    agent = info["agent"]
    sig = ", ".join(r.split(" (")[0] for r in decision["reasons"][:2]) or "default"
    sc = f"{decision['score']}/100 {sig}" if decision["score"] is not None else sig
    ti, si = TIERS.index(tier), TIERS.index(session_tier)
    if ti == si:
        return None
    if ti > si:
        return (f"[router: tier={tier.upper()} ({sc})] Delegate via Agent tool (foreground) to `{agent}` "
                f"({info['model']}) with a compact brief (goal, files, constraints, done criteria). Relay result concisely.")
    return (f"[router: tier={tier.upper()} ({sc})] Easier than {session_tier}. If >2 tool calls or file/shell search needed, "
            f"delegate (foreground) to `{agent}` ({info['model']}); otherwise answer directly in <=8 lines.")

def read_event() -> dict:
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}

def hook_prompt() -> None:
    cfg, state = load_config(), load_state()
    mode = state.get("mode", cfg.get("default_mode", "eco"))
    if mode == "off": return
    ev = read_event()
    prompt = ev.get("prompt", "")
    if prompt.lstrip().startswith("/"): return
    sid = ev.get("session_id", "default")
    sessions = state.setdefault("sessions", {})
    sess = sessions.get(sid, {})
    decision = route(prompt, cfg, mode, sess)
    session_model = current_session_model(ev.get("transcript_path"), sess, cfg)
    session_tier = tier_of_model(session_model) or "haiku"
    sessions[sid] = {**sess, "last_tier": decision["tier"], "ts": time.time(), "model": session_model}
    save_state(state)
    log_decision({"ts": int(time.time()), "session": sid[:8], "tier": decision["tier"],
                  "score": decision["score"], "why": decision["why"], "session_tier": session_tier})
    out: dict = {}
    directive = build_directive(decision, session_tier, cfg)
    if directive:
        out["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit", "additionalContext": directive}
    if cfg.get("show_badge", True):
        icon = {"haiku": "🟢", "sonnet": "🔵", "opus": "🟣", "fable": "🟠"}[decision["tier"]]
        sc = f" · {decision['score']}/100" if decision["score"] is not None else f" · {decision['why']}"
        where = "here" if not directive else f"→ {cfg['tiers'][decision['tier']]['agent']}"
        out["systemMessage"] = f"{icon} router: {decision['tier']}{sc} ({where}, session on {session_tier})"
    if out:
        print(json.dumps(out))

def hook_session() -> None:
    cfg, state = load_config(), load_state()
    mode = state.get("mode", cfg.get("default_mode", "eco"))
    ev = read_event()
    sid = ev.get("session_id", "default")
    model = ev.get("model")
    if isinstance(model, dict): model = model.get("id") or model.get("name")
    if model:
        state.setdefault("sessions", {}).setdefault(sid, {})["model"] = model
        save_state(state)
    if mode == "off": return
    policy = (f"[router mode={mode}] Follow [router: tier=...] notes by delegating (foreground) to router-haiku/sonnet/opus/fable. "
              "No note = solve directly. On 'ESCALATE: <tier>', re-delegate to router-<tier>. Prefer Grep/line-range Read; keep replies concise.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": policy}}))

def _price(tier: str, cfg: dict, u: dict) -> float:
    p, cm = cfg["pricing_per_mtok"][tier], cfg["cache_multipliers"]
    inp, cr, cw, out = u.get("input_tokens", 0) or 0, u.get("cache_read_input_tokens", 0) or 0, u.get("cache_creation_input_tokens", 0) or 0, u.get("output_tokens", 0) or 0
    cw1h = (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0) or 0
    cw5m = max(0, cw - cw1h)
    r = p.get("input_over_100k", p["input"]) if (inp + cr + cw > 100_000) else p["input"]
    return (inp * r + cr * r * cm["read"] + cw5m * r * cm["write_5m"] + cw1h * r * cm["write_1h"] + out * p["output"]) / 1_000_000

def cmd_stats(days: float) -> None:
    cfg, cutoff = load_config(), time.time() - days * 86400
    per_model, seen, actual, bf, bo = {}, set(), 0.0, 0.0, 0.0
    for f in glob.glob(str(CLAUDE_HOME / "projects" / "**" / "*.jsonl"), recursive=True):
        if os.path.getmtime(f) < cutoff: continue
        try:
            with open(f, "rb") as fh:
                for line in fh:
                    if b'"usage"' not in line: continue
                    msg = (json.loads(line).get("message") or {})
                    mid, u, m = msg.get("id"), msg.get("usage"), msg.get("model", "")
                    t = tier_of_model(m)
                    if not (u and t and mid) or mid in seen: continue
                    seen.add(mid); c = _price(t, cfg, u); actual += c; bf += _price("fable", cfg, u); bo += _price("opus", cfg, u)
                    pm = per_model.setdefault(m, {"calls": 0, "in": 0, "out": 0, "cost": 0.0})
                    pm["calls"] += 1; pm["in"] += (u.get("input_tokens", 0) or 0) + (u.get("cache_read_input_tokens", 0) or 0) + (u.get("cache_creation_input_tokens", 0) or 0)
                    pm["out"] += u.get("output_tokens", 0) or 0; pm["cost"] += c
        except Exception: continue
    print(f"{'model':<26}{'calls':>7}{'input tok':>14}{'output tok':>11}{'est. $':>9}")
    for m, pm in sorted(per_model.items(), key=lambda kv: -kv[1]["cost"]):
        print(f"{m:<26}{pm['calls']:>7}{pm['in']:>14,}{pm['out']:>11,}{pm['cost']:>9.2f}")
    if actual:
        print(f"\nActual: ${actual:,.2f} | All-Fable: ${bf:,.2f} (saved {100*(1-actual/bf):.1f}%) | All-Opus: ${bo:,.2f} (saved {100*(1-actual/bo):.1f}%)")

def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd in ("hook-prompt", "hook-session"):
        try: hook_prompt() if cmd == "hook-prompt" else hook_session()
        except Exception: pass
        return 0
    cfg, state = load_config(), load_state()
    mode = state.get("mode", cfg.get("default_mode", "eco"))
    if cmd == "explain":
        d = route(" ".join(argv[2:]) or sys.stdin.read(), cfg, mode, None)
        t = cfg["tiers"][d["tier"]]
        print(f"Mode={mode} | Score={d['score']}/100 | Tier={d['tier'].upper()} -> {t['agent']} ({t['model']}) | Signals: {', '.join(d['reasons'])}")
    elif cmd == "mode":
        if len(argv) > 2 and argv[2] in ("eco", "balanced", "quality", "off"):
            state["mode"] = argv[2]; save_state(state)
        print(f"mode: {state.get('mode', mode)} (eco | balanced | quality | off)")
    elif cmd == "stats":
        days = float(argv[argv.index("--days") + 1]) if ("--days" in argv and len(argv) > argv.index("--days") + 1) else 7.0
        cmd_stats(days)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
