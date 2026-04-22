"""CLI 入口：基于 Click 的命令行界面。"""

import json
import sys
from pathlib import Path
import shutil

import click

from memento import __version__
from memento.core import MementoCore
from memento.export import export_memories, import_memories
from memento.seed import seed_experiment_dataset


_PROVIDER_PRESETS = {
    "zhipu": {
        "embedding_model": "embedding-3",
        "llm_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "llm_model": "glm-4-flash-250414",
    },
    "openai": {
        "embedding_model": "text-embedding-3-small",
        "llm_base_url": "https://api.openai.com/v1",
        "llm_model": "gpt-4o-mini",
    },
}


def _inject_hooks(settings: dict, hook_handler_path: str):
    """Inject memento hooks into settings dict (mutates in place)."""
    hooks = settings.setdefault("hooks", {})
    hook_defs = [
        ("SessionStart", "session-start", 10),
        ("PostToolUse", "observe", 5),
        ("Stop", "flush-and-epoch", 15),
        ("SessionEnd", "session-end", 15),
    ]
    for event, cmd, timeout in hook_defs:
        event_hooks = hooks.setdefault(event, [])
        if any("hook-handler.sh" in h.get("command", "") for h in event_hooks if isinstance(h, dict)):
            continue
        event_hooks.append({
            "type": "command",
            "command": f"{hook_handler_path} {cmd}",
            "timeout": timeout * 1000,
        })


def _get_core(db_path: str | None = None):
    """创建 MementoCore 实例。"""
    return MementoCore(db_path=Path(db_path) if db_path else None)


def _get_api(db=None):
    """创建 MementoAPI (LocalAPI) 实例。"""
    from memento.api import MementoAPI
    from memento.db import get_db_path
    return MementoAPI(db_path=db or get_db_path())


def _build_comparison_report(primary: dict, comparison: dict) -> dict:
    """汇总两组评估结果及差值。"""

    def delta(name: str):
        left = primary.get(name)
        right = comparison.get(name)
        if left is None or right is None:
            return None
        return left - right

    stale_reduction_ratio = None
    primary_stale = primary.get("stale_hit_rate")
    comparison_stale = comparison.get("stale_hit_rate")
    if (
        primary_stale is not None
        and comparison_stale is not None
        and comparison_stale > 0
    ):
        stale_reduction_ratio = (comparison_stale - primary_stale) / comparison_stale

    precision_delta = delta("precision_at_3")
    precision_gate_passed = (
        precision_delta is not None and precision_delta > 0.15
    )
    stale_gate_passed = (
        stale_reduction_ratio is not None and stale_reduction_ratio >= 0.5
    )

    return {
        "primary": primary,
        "comparison": comparison,
        "delta": {
            "precision_at_3": precision_delta,
            "mrr": delta("mrr"),
            "stale_hit_rate": delta("stale_hit_rate"),
        },
        "summary": {
            "stale_hit_rate_reduction_ratio": stale_reduction_ratio,
            "precision_gate_passed": precision_gate_passed,
            "stale_suppression_gate_passed": stale_gate_passed,
            "upgrade_recommended": precision_gate_passed and stale_gate_passed,
        },
    }


def _ensure_target_path(path: Path, force: bool) -> None:
    """检查目标路径是否允许写入。"""
    if path.exists() and not force:
        raise click.ClickException(
            f"目标已存在: {path}，如需覆盖请添加 --force"
        )
    path.parent.mkdir(parents=True, exist_ok=True)


@click.group()
@click.version_option(__version__, prog_name="memento")
def main():
    """Memento — AI Agent 的长期记忆引擎。"""
    pass


@main.command()
@click.option("--yes", "-y", is_flag=True, help="非交互模式")
@click.option("--embedding-provider", type=click.Choice(["local", "zhipu", "openai"]), default=None)
@click.option("--embedding-api-key", default=None)
@click.option("--llm-provider", type=click.Choice(["zhipu", "openai"]), default=None)
@click.option("--llm-api-key", default=None)
@click.option("--llm-base-url", default=None)
@click.option("--llm-model", default=None)
def setup(yes, embedding_provider, embedding_api_key, llm_provider, llm_api_key, llm_base_url, llm_model):
    """交互式安装向导：初始化数据库、配置 Embedding/LLM、集成 Claude Code。"""
    import os
    import stat

    from memento.config import save_config, mask_key
    from memento.db import get_connection, init_db

    home = Path.home()
    cfg = {"database": {}, "embedding": {}, "llm": {}}

    # ── [1/4] Init DB ──
    click.echo("\n[1/4] 初始化数据库...")
    db_path = home / ".memento" / "default.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    init_db(conn)
    conn.close()
    db_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    cfg["database"]["path"] = str(db_path)
    click.echo(f"  数据库: {db_path}")

    # ── [2/4] Configure Embedding ──
    click.echo("\n[2/4] 配置 Embedding...")
    emb_provider = None
    emb_api_key = None

    if yes:
        # Non-interactive: use flags if provided, default to local otherwise
        if embedding_provider:
            emb_provider = embedding_provider
            emb_api_key = embedding_api_key
        else:
            emb_provider = "local"
    else:
        # Interactive
        click.echo("  选择 Embedding 提供商:")
        click.echo("    1) 本地模型（无需 API key，适合快速开始）")
        click.echo("    2) zhipu (智谱)")
        click.echo("    3) openai")
        click.echo("    4) 跳过（仅使用全文搜索）")
        choice = click.prompt("  请选择", type=click.IntRange(1, 4), default=1)
        if choice == 1:
            emb_provider = "local"
            click.echo("  ℹ 本地模型适合快速开始。如主要处理中文内容，")
            click.echo("    建议后续配置云端 provider 以获得更稳定的语义检索质量。")
        elif choice == 2:
            emb_provider = "zhipu"
            emb_api_key = click.prompt("  请输入 Zhipu API Key", hide_input=True)
        elif choice == 3:
            emb_provider = "openai"
            emb_api_key = click.prompt("  请输入 OpenAI API Key", hide_input=True)
        elif choice == 4:
            click.echo("  ⚠️  跳过 Embedding 配置将导致:")
            click.echo("     - 语义检索不可用，仅支持关键词匹配")
            click.echo("     - recall 质量显著下降")
            if not click.confirm("  继续？", default=False):
                raise SystemExit(1)
            emb_provider = "none"

    if emb_provider:
        preset = _PROVIDER_PRESETS.get(emb_provider, {})
        cfg["embedding"]["provider"] = emb_provider
        cfg["embedding"]["api_key"] = emb_api_key
        cfg["embedding"]["model"] = preset.get("embedding_model")
        click.echo(f"  Embedding: {emb_provider} ({preset.get('embedding_model', '?')})")
    else:
        click.echo("  Embedding: 跳过")

    # ── [3/4] Configure LLM ──
    click.echo("\n[3/4] 配置 LLM...")
    llm_prov = None
    llm_key = None
    llm_url = None
    llm_mod = None

    if yes:
        # Non-interactive
        if llm_provider:
            llm_prov = llm_provider
            llm_key = llm_api_key
            llm_url = llm_base_url
            llm_mod = llm_model
    else:
        # Interactive
        click.echo("  选择 LLM 提供商:")
        click.echo("    1) zhipu (智谱)")
        click.echo("    2) openai compatible")
        click.echo("    3) 跳过")
        choice = click.prompt("  请选择", type=click.IntRange(1, 3), default=1)
        if choice == 1:
            llm_prov = "zhipu"
        elif choice == 2:
            llm_prov = "openai"
        else:
            click.echo("  ⚠️  跳过 LLM 配置将导致:")
            click.echo("     - Epoch 整合不可用")
            click.echo("     - 自动记忆提取不可用")
            if not click.confirm("  继续？", default=False):
                raise SystemExit(1)

        if llm_prov:
            # Offer to reuse embedding API key if same provider
            if llm_prov == emb_provider and emb_api_key:
                reuse = click.confirm(f"  与 Embedding 使用相同的 {llm_prov} API Key？", default=True)
                if reuse:
                    llm_key = emb_api_key
                else:
                    llm_key = click.prompt(f"  {llm_prov} API Key", hide_input=True)
            else:
                llm_key = click.prompt(f"  {llm_prov} API Key", hide_input=True)

            # For "openai compatible", additionally prompt for base_url and model
            if llm_prov == "openai":
                preset = _PROVIDER_PRESETS["openai"]
                llm_url = click.prompt("  Base URL", default=preset["llm_base_url"])
                llm_mod = click.prompt("  Model", default=preset["llm_model"])

    if llm_prov:
        preset = _PROVIDER_PRESETS.get(llm_prov, {})
        cfg["llm"]["provider"] = llm_prov
        cfg["llm"]["api_key"] = llm_key
        cfg["llm"]["base_url"] = llm_url or preset.get("llm_base_url")
        cfg["llm"]["model"] = llm_mod or preset.get("llm_model")
        click.echo(f"  LLM: {llm_prov} ({cfg['llm']['model']})")
    else:
        click.echo("  LLM: 跳过")

    # ── [4/4] Claude Code Integration ──
    click.echo("\n[4/4] 集成 Claude Code...")

    # Find hook-handler.sh
    hook_handler = _find_hook_handler()
    if hook_handler:
        handler_path = str(hook_handler)

        # Write hooks to ~/.claude/settings.json
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_file = claude_dir / "settings.json"

        settings = {}
        if settings_file.exists():
            try:
                settings = json.loads(settings_file.read_text())
            except json.JSONDecodeError:
                settings = {}

        _inject_hooks(settings, handler_path)
        settings_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        click.echo(f"  Hooks: {settings_file}")

        # Write MCP to ~/.claude/.mcp.json
        mcp_file = claude_dir / ".mcp.json"
        mcp_config = {}
        if mcp_file.exists():
            try:
                mcp_config = json.loads(mcp_file.read_text())
            except json.JSONDecodeError:
                mcp_config = {}

        servers = mcp_config.setdefault("mcpServers", {})
        if "memento" not in servers:
            mcp_cmd = shutil.which("memento-mcp-server")
            if mcp_cmd:
                servers["memento"] = {
                    "type": "stdio",
                    "command": mcp_cmd,
                    "args": [],
                }
            else:
                # fallback: python -m memento.mcp_server
                servers["memento"] = {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": [str(Path(__file__).parent / "mcp_server.py")],
                }
            mcp_config["mcpServers"] = servers
            mcp_file.write_text(json.dumps(mcp_config, indent=2, ensure_ascii=False) + "\n")
        click.echo(f"  MCP: {mcp_file}")

        # Check for project-level hooks conflict
        project_settings = Path.cwd() / ".claude" / "settings.json"
        if project_settings.exists():
            try:
                proj = json.loads(project_settings.read_text())
                proj_hooks = proj.get("hooks", {})
                if any("hook-handler.sh" in str(v) for v in json.dumps(proj_hooks).split(",")):
                    click.echo("  ⚠️  检测到项目级 hooks 中也包含 memento，可能产生冲突。")
            except (json.JSONDecodeError, OSError):
                pass
    else:
        click.echo("  ⚠️  未找到 hook-handler.sh，跳过 Claude Code 集成。")

    # ── Save config & print summary ──
    config_path = save_config(cfg)

    click.echo(f"\n{'─' * 50}")
    click.echo("✅ Memento 安装完成！")
    click.echo(f"   配置文件: {config_path}")
    if emb_provider and emb_api_key:
        click.echo(f"   Embedding API Key: {mask_key(emb_api_key)}")
    if llm_prov and llm_key:
        click.echo(f"   LLM API Key: {mask_key(llm_key)}")
    click.echo(f"\n   建议运行: memento doctor  (检查环境)")
    click.echo(f"{'─' * 50}\n")


@main.command()
@click.option("--ping", is_flag=True, help="主动验证外部服务连通性（会发真实请求）")
def doctor(ping):
    """检查 Memento 配置状态。"""
    import hashlib
    import os
    import stat
    import time

    from memento.config import get_config, mask_key, CONFIG_PATH

    home = Path.home()
    errors = 0
    warnings = 0

    click.echo("\n═══ Memento Doctor ═══\n")

    # ── 1. Config file ──
    config_path = CONFIG_PATH()
    if config_path.exists():
        click.echo(f"  配置文件     {config_path}          ✓ 存在")
    else:
        click.echo(f"  配置文件     {config_path}          ✗ 未找到")
        errors += 1

    # Load config for subsequent checks
    cfg = get_config()

    # ── 2. Database ──
    db_path_str = cfg.get("database", {}).get("path", "")
    db_path = Path(db_path_str) if db_path_str else home / ".memento" / "default.db"
    if db_path.exists():
        try:
            mode = stat.S_IMODE(os.stat(db_path).st_mode)
            mode_str = oct(mode)
            click.echo(f"  数据库       {db_path}          ✓ 可读写 (权限 {mode_str})")
        except OSError:
            click.echo(f"  数据库       {db_path}          ✗ 无法读取")
            errors += 1
    else:
        click.echo(f"  数据库       {db_path}          ✗ 不存在")
        errors += 1

    # ── 3. Embedding ──
    emb_cfg = cfg.get("embedding", {})
    provider = emb_cfg.get("provider")

    if provider == "local":
        try:
            from sentence_transformers import SentenceTransformer
            click.echo("  Embedding    local (all-MiniLM-L6-v2, 384d)          ✓")
        except ImportError:
            click.echo("  Embedding    local                                   ⚠ sentence-transformers not installed")
            click.echo("               Run: pip install memento[local]")
            warnings += 1
    elif provider == "none":
        click.echo("  Embedding    skipped (full-text search only)        ✓")
    elif provider is None:
        click.echo("  Embedding    no provider configured                  ⚠ run `memento setup`")
        warnings += 1
    elif provider in ("zhipu", "minimax", "moonshot", "openai", "gemini"):
        api_key = emb_cfg.get("api_key")
        if api_key:
            click.echo(f"  Embedding    {provider} (key: {mask_key(api_key)})          ✓")
        else:
            click.echo(f"  Embedding    {provider}                              ⚠ API key missing")
            warnings += 1
    else:
        click.echo(f"  Embedding    unknown provider '{provider}'          ⚠")
        warnings += 1

    # ── 4. LLM ──
    llm_cfg = cfg.get("llm", {})
    llm_provider = llm_cfg.get("provider", "未配置")
    llm_model = llm_cfg.get("model", "?")
    llm_label = f"{llm_provider} ({llm_model})" if llm_provider else "未配置"

    if ping:
        try:
            from memento.llm import LLMClient
            t0 = time.time()
            client = LLMClient.from_config()
            if client is None:
                raise RuntimeError("LLM 未配置")
            client.generate("ping")
            latency = (time.time() - t0) * 1000
            click.echo(f"  LLM          {llm_label}          ✓ 连通 ({latency:.0f}ms)")
        except Exception as e:
            click.echo(f"  LLM          {llm_label}          ⚠ 连接失败: {e}")
            warnings += 1
    else:
        if llm_cfg.get("api_key"):
            click.echo(f"  LLM          {llm_label}          ✓ 已配置")
        else:
            click.echo(f"  LLM          {llm_label}          ⚠ 未配置 API Key")
            warnings += 1

    # ── 5. Hooks ──
    settings_path = home / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})
            expected_events = ["SessionStart", "PostToolUse", "Stop", "SessionEnd"]
            found = 0
            for event in expected_events:
                event_hooks = hooks.get(event, [])
                # Check both old format (list of dicts with "command") and new format (list of dicts with "hooks")
                has_memento = False
                for h in event_hooks:
                    if isinstance(h, dict):
                        if "hook-handler.sh" in h.get("command", ""):
                            has_memento = True
                            break
                        for sub in h.get("hooks", []):
                            if isinstance(sub, dict) and "hook-handler.sh" in sub.get("command", ""):
                                has_memento = True
                                break
                    if has_memento:
                        break
                if has_memento:
                    found += 1
            if found == 4:
                click.echo(f"  Hooks        {settings_path}          ✓ {found}/4 已安装")
            else:
                click.echo(f"  Hooks        {settings_path}          ✗ {found}/4 已安装")
                errors += 1
        except (json.JSONDecodeError, OSError):
            click.echo(f"  Hooks        {settings_path}          ✗ 文件读取失败")
            errors += 1
    else:
        click.echo(f"  Hooks        {settings_path}          ✗ 未找到")
        errors += 1

    # ── 6. MCP Server ──
    mcp_path = home / ".claude" / ".mcp.json"
    if mcp_path.exists():
        try:
            mcp_config = json.loads(mcp_path.read_text())
            servers = mcp_config.get("mcpServers", {})
            if "memento" in servers:
                click.echo(f"  MCP Server   {mcp_path}          ✓ 已配置")
            else:
                click.echo(f"  MCP Server   {mcp_path}          ✗ 未找到 memento 条目")
                errors += 1
        except (json.JSONDecodeError, OSError):
            click.echo(f"  MCP Server   {mcp_path}          ✗ 文件读取失败")
            errors += 1
    else:
        click.echo(f"  MCP Server   {mcp_path}          ✗ 未找到")
        errors += 1

    # ── 7. Worker ──
    db_abs = str(Path(db_path).resolve())
    sock_hash = hashlib.md5(db_abs.encode()).hexdigest()[:12]
    sock_path = f"/tmp/memento-worker-{sock_hash}.sock"
    if Path(sock_path).exists():
        click.echo(f"  Worker       {sock_path}          ✓ 运行中")
    else:
        click.echo(f"  Worker       {sock_path}          ✗ 未运行（首次 hook 触发时自动启动）")
        warnings += 1

    # ── Summary ──
    click.echo(f"\n═══ {warnings} 个警告，{errors} 个错误 ═══\n")


@main.command()
def init():
    """初始化 Memento 数据库。"""
    from memento.db import get_db_path

    core = _get_core()
    db_path = get_db_path()
    core.close()
    click.echo("✅ Memento 数据库已初始化。")
    click.echo(f"   路径: {db_path}")


@main.command()
@click.argument("content")
@click.option("--type", "type_", default="fact", help="记忆类型: fact|decision|insight|convention|debugging|preference")
@click.option("--importance", default="normal", help="重要性: low|normal|high|critical")
@click.option("--tags", default=None, help="标签，逗号分隔: react,auth")
@click.option("--origin", default="human", help="来源: human|agent")
def capture(content: str, type_: str, importance: str, tags: str | None, origin: str):
    """写入一条记忆。"""
    import os
    from memento.api import MementoAPI

    api = MementoAPI()
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    session_id = os.environ.get("MEMENTO_SESSION_ID")

    engram_id = api.capture(
        content, type=type_, importance=importance,
        tags=tag_list, origin=origin, session_id=session_id,
    )
    api.close()

    click.echo(f"Captured to L2 (buffered): {engram_id}")


@main.command()
@click.argument("query")
@click.option("--max", "max_results", default=5, help="最大返回数量")
@click.option("--mode", default=None, hidden=True, help="[已废弃] 检索模式")
@click.option("--db", "db_path", type=click.Path(), default=None, help="数据库路径（默认使用 MEMENTO_DB 或 ~/.memento/default.db）")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
@click.option("--reinforce", is_flag=True, default=False, hidden=True, help="[已废弃] 启用再巩固")
def recall(query: str, max_results: int, mode: str | None, db_path: str | None, fmt: str, reinforce: bool):
    """检索记忆（带衰减权重，默认只读）。"""
    if mode is not None:
        click.echo("⚠️  --mode 参数已废弃，将在未来版本移除。", err=True)
    if reinforce:
        click.echo("⚠️  --reinforce 参数已废弃，将在未来版本移除。", err=True)

    api = _get_api(db_path)
    results = api.recall(query, max_results=max_results, reinforce=False)
    api.close()

    if not results:
        click.echo("未找到相关记忆。")
        return

    if fmt == "json":
        data = []
        for r in results:
            # awake mode returns dicts, legacy returns RecallResult objects
            if isinstance(r, dict):
                d = {
                    "id": r.get("id"),
                    "content": r.get("content"),
                    "type": r.get("type"),
                    "tags": r.get("tags"),
                    "strength": r.get("score", 0),
                    "score": r.get("score", 0),
                    "mode": "A",
                    "importance": r.get("importance"),
                    "origin": r.get("origin"),
                    "verified": r.get("verified", False),
                    "provisional": r.get("provisional", False),
                }
            else:
                d = {
                    "id": r.id,
                    "content": r.content,
                    "type": r.type,
                    "tags": r.tags,
                    "strength": r.strength,
                    "score": r.score,
                    "mode": "A",
                    "importance": r.importance,
                    "origin": r.origin,
                    "verified": r.verified,
                }
                if r.review_hint:
                    d["review_hint"] = r.review_hint
            data.append(d)
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(results, 1):
            if isinstance(r, dict):
                click.echo(f"\n{'─' * 60}")
                click.echo(f"  [{i}] {r.get('content', '')}")
                click.echo(f"      类型: {r.get('type', '?')} | 得分: {r.get('score', 0):.4f}")
                click.echo(f"      标签: {r.get('tags') or '无'}")
                click.echo(f"      来源: {r.get('origin', '?')} | 临时: {'是' if r.get('provisional') else '否'}")
                click.echo(f"      ID: {r.get('id')}")
            else:
                click.echo(f"\n{'─' * 60}")
                click.echo(f"  [{i}] {r.content}")
                click.echo(f"      类型: {r.type} | 强度: {r.strength:.2f} | 得分: {r.score:.4f}")
                click.echo(f"      标签: {', '.join(r.tags) if r.tags else '无'}")
                click.echo(f"      来源: {r.origin} | 已验证: {'是' if r.verified else '否'}")
                click.echo(f"      ID: {r.id}")
                if r.review_hint:
                    click.echo(f"      ⚠️  {r.review_hint}")
        click.echo(f"\n{'─' * 60}")
        click.echo(f"共 {len(results)} 条结果。")


@main.command()
@click.option("--db", "db_path", type=click.Path(), default=None, help="数据库路径（建议使用新的实验库）")
@click.option("--queries-output", type=click.Path(), default="examples/eval_queries.generated.json", help="生成的查询集 JSON 路径")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def seed_experiment(db_path: str | None, queries_output: str, fmt: str):
    """生成 v0.1 实验用的种子数据和查询集。"""
    core = _get_core(db_path)
    report = seed_experiment_dataset(core, Path(queries_output))
    core.close()

    if fmt == "json":
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    click.echo("\n实验种子已生成")
    click.echo(f"{'─' * 40}")
    click.echo(f"  写入记忆数:        {report['inserted']}")
    click.echo(f"  查询集路径:        {report['queries_output']}")
    click.echo(f"{'─' * 40}\n")


@main.command()
@click.option("--db-a", type=click.Path(), default="eval_mode_a.db", help="实验组数据库路径")
@click.option("--db-b", type=click.Path(), default="eval_mode_b.db", help="基线组数据库路径")
@click.option("--queries-output", type=click.Path(), default="examples/eval_queries.generated.json", help="生成的查询集 JSON 路径")
@click.option("--manifest-output", type=click.Path(), default="examples/experiment_manifest.generated.json", help="实验清单 JSON 路径")
@click.option("--force", is_flag=True, help="覆盖已存在的输出文件")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def setup_experiment(
    db_a: str,
    db_b: str,
    queries_output: str,
    manifest_output: str,
    force: bool,
    fmt: str,
):
    """一键初始化 v0.1 A/B 实验所需的数据库和查询集。"""
    db_a_path = Path(db_a)
    db_b_path = Path(db_b)
    queries_path = Path(queries_output)
    manifest_path = Path(manifest_output)

    _ensure_target_path(db_a_path, force)
    _ensure_target_path(db_b_path, force)
    _ensure_target_path(queries_path, force)
    _ensure_target_path(manifest_path, force)

    core = _get_core(str(db_a_path))
    seed_report = seed_experiment_dataset(core, queries_path)
    core.close()

    shutil.copy2(db_a_path, db_b_path)

    manifest = {
        "db_a": str(db_a_path),
        "db_b": str(db_b_path),
        "queries": str(queries_path),
        "seed": seed_report,
        "recommended_eval": {
            "primary": f"memento eval --queries {queries_path} --db {db_a_path} --mode A --compare-db {db_b_path} --compare-mode B --format json",
            "midterm": "Day 7: 关注过时抑制率和冷记忆下沉",
            "final": "Day 14: 对 Precision@3、MRR、过时抑制率做最终判断",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if fmt == "json":
        click.echo(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    click.echo("\n实验初始化完成")
    click.echo(f"{'─' * 40}")
    click.echo(f"  实验组数据库:      {db_a_path}")
    click.echo(f"  基线组数据库:      {db_b_path}")
    click.echo(f"  查询集路径:        {queries_path}")
    click.echo(f"  清单路径:          {manifest_path}")
    click.echo(f"{'─' * 40}\n")


@main.command()
@click.option("--queries", "queries_file", type=click.Path(exists=True), required=True, help="评估查询集 JSON 文件")
@click.option("--max", "max_results", default=5, help="每条查询返回的最大结果数")
@click.option("--mode", type=click.Choice(["A", "B"], case_sensitive=False), default="A", help="评估模式")
@click.option("--db", "db_path", type=click.Path(), default=None, help="数据库路径（建议使用评估副本）")
@click.option("--compare-db", type=click.Path(exists=True), default=None, help="对照数据库路径")
@click.option("--compare-mode", type=click.Choice(["A", "B"], case_sensitive=False), default="B", help="对照数据库的评估模式")
@click.option("--report-output", type=click.Path(), default=None, help="将完整 JSON 报告写入文件")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def eval_cmd(
    queries_file: str,
    max_results: int,
    mode: str,
    db_path: str | None,
    compare_db: str | None,
    compare_mode: str,
    report_output: str | None,
    fmt: str,
):
    """对标注查询集执行只读评估。"""
    with open(queries_file, "r", encoding="utf-8") as f:
        raw_queries = json.load(f)

    queries = []
    for item in raw_queries:
        if isinstance(item, str):
            queries.append({"query": item})
        else:
            queries.append(item)

    core = _get_core(db_path)
    report = core.evaluate(queries, max_results=max_results, mode=mode)
    core.close()

    output: dict = report
    if compare_db:
        compare_core = _get_core(compare_db)
        comparison = compare_core.evaluate(
            queries,
            max_results=max_results,
            mode=compare_mode,
        )
        compare_core.close()
        output = _build_comparison_report(report, comparison)

    if report_output:
        report_path = Path(report_output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if fmt == "json":
        click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        return

    if compare_db:
        primary = output["primary"]
        comparison = output["comparison"]
        delta = output["delta"]
        summary = output["summary"]
        click.echo("\n对比评估结果")
        click.echo(f"{'─' * 48}")
        click.echo(f"  主评估:            {primary['mode']} @ {db_path or 'default'}")
        click.echo(f"  对照评估:          {comparison['mode']} @ {compare_db}")
        click.echo(f"  Precision@3 差值:  {delta['precision_at_3'] if delta['precision_at_3'] is not None else 'n/a'}")
        click.echo(f"  MRR 差值:          {delta['mrr'] if delta['mrr'] is not None else 'n/a'}")
        click.echo(f"  过时命中率差值:    {delta['stale_hit_rate'] if delta['stale_hit_rate'] is not None else 'n/a'}")
        click.echo(f"  过时抑制比例:      {summary['stale_hit_rate_reduction_ratio'] if summary['stale_hit_rate_reduction_ratio'] is not None else 'n/a'}")
        click.echo(f"  Precision 门槛:    {'pass' if summary['precision_gate_passed'] else 'fail'}")
        click.echo(f"  过时抑制门槛:      {'pass' if summary['stale_suppression_gate_passed'] else 'fail'}")
        click.echo(f"  建议升级 v0.2:     {'yes' if summary['upgrade_recommended'] else 'no'}")
        click.echo(f"{'─' * 48}\n")
        return

    click.echo("\n评估结果")
    click.echo(f"{'─' * 40}")
    click.echo(f"  模式:              {output['mode']}")
    click.echo(f"  查询数:            {output['query_count']}")
    click.echo(f"  标注查询数:        {output['labeled_count']}")
    click.echo(f"  过时标注查询数:    {output['stale_labeled_count']}")
    click.echo(f"  Precision@3:       {output['precision_at_3'] if output['precision_at_3'] is not None else 'n/a'}")
    click.echo(f"  MRR:               {output['mrr'] if output['mrr'] is not None else 'n/a'}")
    click.echo(f"  过时命中率:        {output['stale_hit_rate'] if output['stale_hit_rate'] is not None else 'n/a'}")
    click.echo(f"{'─' * 40}\n")


@main.command()
@click.argument("engram_id")
def verify(engram_id: str):
    """人类确认某条 Agent 记忆为可信。"""
    api = _get_api()
    result = api.verify(engram_id)
    api.close()

    # awake mode returns dict, legacy returns bool
    if isinstance(result, dict):
        click.echo(f"✅ 记忆 {engram_id} 已标记为已验证。")
    elif result:
        click.echo(f"✅ 记忆 {engram_id} 已标记为已验证。")
    else:
        click.echo(f"⚠️  未找到未验证的记忆 {engram_id}。")


@main.command()
@click.argument("engram_id")
def forget(engram_id: str):
    """标记一条记忆为遗忘。"""
    api = _get_api()
    result = api.forget(engram_id)
    api.close()

    # awake mode returns dict, legacy returns bool
    if isinstance(result, dict):
        click.echo(f"Marked for deletion. Will take effect after next epoch run.")
    elif result:
        click.echo(f"Marked for deletion. Will take effect after next epoch run.")
    else:
        click.echo(f"⚠️  未找到活跃记忆 {engram_id}。")


@main.command()
def status():
    """显示数据库统计信息。"""
    api = _get_api()
    stats = api.status()
    api.close()

    click.echo("\n📊 Memento 状态")
    click.echo(f"{'─' * 40}")
    click.echo(f"  总记忆数:         {stats.total}")
    click.echo(f"  活跃:             {stats.active}")
    click.echo(f"  已遗忘:           {stats.forgotten}")
    click.echo(f"  Agent 未验证:     {stats.unverified_agent}")
    click.echo(f"  已生成 Embedding: {stats.with_embedding}")
    click.echo(f"  Embedding 待补填: {stats.pending_embedding}")
    if stats.total_sessions is not None:
        click.echo(f"{'─' * 40}")
        click.echo(f"  总会话数:         {stats.total_sessions}")
        click.echo(f"  活跃会话:         {stats.active_sessions}")
        click.echo(f"  已完成会话:       {stats.completed_sessions}")
        click.echo(f"  总 Observation:   {stats.total_observations}")
    # v0.5 新增统计
    click.echo(f"{'─' * 40}")
    if stats.by_state:
        click.echo(f"  按状态分布:       {json.dumps(stats.by_state, ensure_ascii=False)}")
    click.echo(f"  待处理 Capture:   {stats.pending_capture}")
    click.echo(f"  待处理 Delta:     {stats.pending_delta}")
    click.echo(f"  认知债务数:       {stats.cognitive_debt_count}")
    if stats.last_epoch_committed_at:
        click.echo(f"  最后 Epoch:       {stats.last_epoch_committed_at}")
    click.echo(f"{'─' * 40}\n")


@main.command("export")
@click.option("--output", "-o", default=None, help="输出文件路径（默认输出到 stdout）")
@click.option("--filter-type", default=None, help="按类型过滤")
@click.option("--filter-tags", default=None, help="按标签过滤，逗号分隔")
def export_cmd(output: str | None, filter_type: str | None, filter_tags: str | None):
    """导出记忆为 JSON。"""
    core = _get_core()
    tag_list = [t.strip() for t in filter_tags.split(",")] if filter_tags else None
    memories = export_memories(core, filter_type=filter_type, filter_tags=tag_list)
    core.close()

    data = json.dumps(memories, ensure_ascii=False, indent=2)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(data)
        click.echo(f"✅ 已导出 {len(memories)} 条记忆到 {output}")
    else:
        click.echo(data)


@main.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("--source", default=None, help="标记导入来源（如作者名）")
def import_cmd(file: str, source: str | None):
    """从 JSON 文件导入记忆。"""
    with open(file, "r", encoding="utf-8") as f:
        memories = json.load(f)

    core = _get_core()
    result = import_memories(core, memories, source=source)
    core.close()

    click.echo(f"✅ 导入完成: {result['imported']} 条新增, {result['skipped']} 条跳过（已存在）。")


# ── v0.2: Session 子命令组 ──

@main.group()
def session():
    """会话生命周期管理。"""
    pass


@session.command("start")
@click.option("--project", default=None, help="项目路径或标识")
@click.option("--task", default=None, help="任务描述")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def session_start(project: str | None, task: str | None, fmt: str):
    """创建新会话并返回 priming 记忆。"""
    from memento.api import MementoAPI

    api = MementoAPI()
    result = api.session_start(project=project, task=task)
    api.close()

    if fmt == "json":
        data = {
            "session_id": result.session_id,
            "project": result.project,
            "task": result.task,
            "priming_memories": [
                {
                    "id": m.id,
                    "content": m.content,
                    "type": m.type,
                    "score": m.score,
                }
                for m in result.priming_memories
            ],
        }
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        click.echo(f"✅ 会话已创建。")
        click.echo(f"   Session ID: {result.session_id}")
        if result.priming_memories:
            click.echo(f"   Priming 记忆 ({len(result.priming_memories)} 条):")
            for m in result.priming_memories:
                click.echo(f"     - [{m.type}] {m.content[:60]}...")


@session.command("end")
@click.argument("session_id")
@click.option("--outcome", default="completed", help="结果: completed|abandoned|error")
@click.option("--summary", default=None, help="会话摘要")
def session_end(session_id: str, outcome: str, summary: str | None):
    """结束会话并存储摘要。"""
    from memento.api import MementoAPI

    api = MementoAPI()
    result = api.session_end(session_id, outcome=outcome, summary=summary)
    api.close()

    if result is None:
        click.echo(f"⚠️  未找到活跃会话 {session_id}。")
        return

    click.echo(f"✅ 会话已结束。")
    click.echo(f"   状态: {result.status}")
    click.echo(f"   Capture 数: {result.captures_count}")
    click.echo(f"   Observation 数: {result.observations_count}")


@session.command("status")
@click.argument("session_id", required=False)
def session_status(session_id: str | None):
    """查看会话详情或当前活跃会话。"""
    from memento.api import MementoAPI

    api = MementoAPI()
    info = api.session_status(session_id)
    api.close()

    if not info:
        click.echo("未找到会话。" if session_id else "无活跃会话。")
        return

    click.echo(f"\n会话详情")
    click.echo(f"{'─' * 40}")
    click.echo(f"  ID:       {info.id}")
    click.echo(f"  项目:     {info.project or '未指定'}")
    click.echo(f"  任务:     {info.task or '未指定'}")
    click.echo(f"  状态:     {info.status}")
    click.echo(f"  开始:     {info.started_at}")
    if info.ended_at:
        click.echo(f"  结束:     {info.ended_at}")
    if info.summary:
        click.echo(f"  摘要:     {info.summary}")
    if info.event_counts:
        click.echo(f"  事件统计: {info.event_counts}")
    click.echo(f"{'─' * 40}\n")


@session.command("list")
@click.option("--project", default=None, help="按项目过滤")
@click.option("--limit", default=10, help="最大返回数量")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def session_list(project: str | None, limit: int, fmt: str):
    """列出最近会话。"""
    from memento.api import MementoAPI

    api = MementoAPI()
    sessions = api.session_list(project=project, limit=limit)
    api.close()

    if not sessions:
        click.echo("无会话记录。")
        return

    if fmt == "json":
        data = [
            {
                "id": s.id,
                "project": s.project,
                "task": s.task,
                "status": s.status,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
            }
            for s in sessions
        ]
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for s in sessions:
            status_icon = {"active": "🟢", "completed": "✅", "abandoned": "⚪", "error": "🔴"}.get(s.status, "❓")
            click.echo(f"  {status_icon} {s.id[:8]}  {s.status:<12} {s.started_at[:16]}  {s.task or ''}")
        click.echo(f"\n共 {len(sessions)} 条会话。")


# ── v0.2: Observe 命令 ──

@main.command()
@click.argument("content")
@click.option("--tool", default=None, help="工具名称")
@click.option("--files", default=None, help="涉及文件，逗号分隔")
@click.option("--tags", default=None, help="标签，逗号分隔")
@click.option("--importance", default="normal", help="重要性: low|normal|high|critical")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def observe(content: str, tool: str | None, files: str | None, tags: str | None, importance: str, fmt: str):
    """写入 observation（经去重/晋升 pipeline 处理）。"""
    import os
    from memento.api import MementoAPI

    api = MementoAPI()
    file_list = [f.strip() for f in files.split(",")] if files else None
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    session_id = os.environ.get("MEMENTO_SESSION_ID")

    result = api.ingest_observation(
        content=content,
        tool=tool,
        files=file_list,
        tags=tag_list,
        session_id=session_id,
        importance=importance,
    )
    api.close()

    if fmt == "json":
        data = {
            "event_id": result.event_id or None,
            "promoted": result.promoted,
            "engram_id": result.engram_id,
            "merged_with": result.merged_with,
            "skipped": result.skipped,
        }
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        if result.skipped:
            if not session_id and not result.promoted:
                click.echo("⚠️  无活跃会话且未达晋升条件，observation 未持久化。")
            else:
                click.echo("⏭️  重复 observation，已跳过。")
        elif result.merged_with:
            click.echo(f"🔄 已合并到已有记忆 {result.merged_with[:8]}...")
        elif result.promoted:
            click.echo(f"⬆️  已晋升为长期记忆。")
            click.echo(f"   Engram ID: {result.engram_id}")
        elif result.event_id:
            click.echo(f"📝 Observation 已记录（未晋升）。")
            click.echo(f"   Event ID: {result.event_id}")
        else:
            click.echo("⚠️  无活跃会话且未达晋升条件，observation 未持久化。")


# ── v0.5: Epoch 子命令组 ──

@main.group()
def epoch():
    """Epoch management commands."""
    pass


@epoch.command("run")
@click.option("--mode", type=click.Choice(["full", "light"]), default="full", help="Epoch 模式")
@click.option("--trigger", type=click.Choice(["manual", "scheduled", "auto"]), default="manual", help="触发方式")
@click.option("--db", default=None, help="数据库路径")
def epoch_run(mode, trigger, db):
    """触发一次 epoch 运行。"""
    api = _get_api(db)
    try:
        result = api.epoch_run(mode=mode, trigger=trigger)
        api.close()
    except Exception as e:
        api.close()
        raise click.ClickException(str(e))

    if result.get("error"):
        click.echo(f"⚠️  {result['error']}")
    else:
        click.echo(f"✅ Epoch 完成。")
        click.echo(f"   ID: {result['epoch_id']}")
        click.echo(f"   模式: {result['mode']}")
        click.echo(f"   状态: {result['status']}")


@epoch.command("status")
@click.option("--db", default=None, help="数据库路径")
def epoch_status(db):
    """查看最近 epoch 运行记录。"""
    api = _get_api(db)
    records = api.epoch_status()
    api.close()

    if not records:
        click.echo("无 epoch 运行记录。")
        return

    for r in records:
        click.echo(f"  {r.get('id', '?')[:12]}  {r.get('status', '?'):<12} "
                    f"{r.get('mode', '?'):<6} {r.get('committed_at') or r.get('lease_acquired', '?')}")
    click.echo(f"\n共 {len(records)} 条记录。")


@epoch.command("debt")
@click.option("--db", default=None, help="数据库路径")
def epoch_debt(db):
    """查看未解决的 cognitive debt。"""
    api = _get_api(db)
    debt = api.epoch_debt()
    api.close()

    if not debt:
        click.echo("无未解决的 cognitive debt。")
        return

    click.echo("\n📋 Cognitive Debt")
    click.echo(f"{'─' * 40}")
    for debt_type, count in debt.items():
        click.echo(f"  {debt_type}: {count}")
    click.echo(f"{'─' * 40}\n")


# ── v0.5: inspect 命令 ──

@main.command()
@click.argument("engram_id")
@click.option("--db", default=None, help="数据库路径")
def inspect(engram_id, db):
    """查看单条 engram 的详细信息。"""
    api = _get_api(db)
    result = api.inspect(engram_id)
    api.close()

    if not result:
        click.echo(f"⚠️  未找到 engram {engram_id}。")
        return

    click.echo(f"\n🔍 Engram 详情")
    click.echo(f"{'─' * 50}")
    click.echo(f"  ID:         {result.get('id')}")
    click.echo(f"  Content:    {result.get('content', '')[:100]}")
    click.echo(f"  State:      {result.get('state', 'unknown')}")
    click.echo(f"  Strength:   {result.get('strength', 0):.4f}")
    click.echo(f"  Rigidity:   {result.get('rigidity', 0):.4f}")
    click.echo(f"  Type:       {result.get('type', 'unknown')}")
    click.echo(f"  Origin:     {result.get('origin', 'unknown')}")
    click.echo(f"  Verified:   {'是' if result.get('verified') else '否'}")

    nexus_list = result.get("nexus", [])
    if nexus_list:
        click.echo(f"{'─' * 50}")
        click.echo(f"  Nexus 连接 ({len(nexus_list)}):")
        for n in nexus_list:
            other = n.get("target_id") if n.get("source_id") == engram_id else n.get("source_id")
            click.echo(f"    -> {other}  [{n.get('type')}] strength={n.get('association_strength', 0):.2f}")

    if result.get("pending_forget"):
        click.echo(f"  ⚠️  此 engram 已标记待删除。")
    click.echo(f"{'─' * 50}\n")


# ── v0.5: nexus 命令 ──

@main.command()
@click.argument("engram_id")
@click.option("--depth", type=click.Choice(["1", "2"]), default="1", help="查询深度")
@click.option("--include-invalidated", is_flag=True, default=False, help="包含已失效的关联")
@click.option("--db", default=None, help="数据库路径")
def nexus(engram_id, depth, include_invalidated, db):
    """查看 engram 的 nexus 连接图。"""
    api = _get_api(db)
    conn = api.conn

    try:
        if depth == "1":
            if include_invalidated:
                rows = conn.execute(
                    "SELECT * FROM nexus WHERE source_id=? OR target_id=?",
                    (engram_id, engram_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nexus WHERE (source_id=? OR target_id=?) "
                    "AND invalidated_at IS NULL",
                    (engram_id, engram_id),
                ).fetchall()
        else:
            # 2-hop recursive CTE
            if include_invalidated:
                rows = conn.execute("""
                    WITH RECURSIVE hop(node, depth, path) AS (
                        SELECT ?, 0, ?
                        UNION ALL
                        SELECT
                            CASE WHEN n.source_id = hop.node THEN n.target_id ELSE n.source_id END,
                            hop.depth + 1,
                            hop.path || ',' || CASE WHEN n.source_id = hop.node THEN n.target_id ELSE n.source_id END
                        FROM nexus n
                        JOIN hop ON (n.source_id = hop.node OR n.target_id = hop.node)
                        WHERE hop.depth < 2
                          AND instr(hop.path, CASE WHEN n.source_id = hop.node THEN n.target_id ELSE n.source_id END) = 0
                    )
                    SELECT DISTINCT n.* FROM nexus n
                    JOIN hop ON (n.source_id = hop.node OR n.target_id = hop.node)
                    WHERE hop.depth >= 0
                """, (engram_id, engram_id)).fetchall()
            else:
                rows = conn.execute("""
                    WITH RECURSIVE hop(node, depth, path) AS (
                        SELECT ?, 0, ?
                        UNION ALL
                        SELECT
                            CASE WHEN n.source_id = hop.node THEN n.target_id ELSE n.source_id END,
                            hop.depth + 1,
                            hop.path || ',' || CASE WHEN n.source_id = hop.node THEN n.target_id ELSE n.source_id END
                        FROM nexus n
                        JOIN hop ON (n.source_id = hop.node OR n.target_id = hop.node)
                        WHERE hop.depth < 2
                          AND n.invalidated_at IS NULL
                          AND instr(hop.path, CASE WHEN n.source_id = hop.node THEN n.target_id ELSE n.source_id END) = 0
                    )
                    SELECT DISTINCT n.* FROM nexus n
                    JOIN hop ON (n.source_id = hop.node OR n.target_id = hop.node)
                    WHERE hop.depth >= 0 AND n.invalidated_at IS NULL
                """, (engram_id, engram_id)).fetchall()

        results = [dict(r) for r in rows]
    except Exception:
        results = []

    api.close()

    if not results:
        click.echo(f"无 nexus 连接。")
        return

    click.echo(f"\n🔗 Nexus 连接 (depth={depth})")
    click.echo(f"{'─' * 60}")
    for n in results:
        click.echo(f"  {n.get('source_id', '?')[:12]} -> {n.get('target_id', '?')[:12]}  "
                    f"[{n.get('type', '?')}] strength={n.get('association_strength', 0):.2f}")
    click.echo(f"{'─' * 60}")
    click.echo(f"共 {len(results)} 条连接。\n")


# ── v0.5: pin 命令 ──

@main.command()
@click.argument("engram_id")
@click.option("--rigidity", required=True, type=float, help="Rigidity 值 (0.0-1.0)")
@click.option("--db", default=None, help="数据库路径")
def pin(engram_id, rigidity, db):
    """设置 engram 的 rigidity（钉住）。"""
    if not (0.0 <= rigidity <= 1.0):
        raise click.ClickException("rigidity 值必须在 0.0 到 1.0 之间。")

    api = _get_api(db)
    try:
        result = api.pin(engram_id, rigidity)
        api.close()
    except Exception as e:
        api.close()
        raise click.ClickException(str(e))

    click.echo(f"✅ Engram {engram_id} rigidity 已设置为 {rigidity:.2f}。")


# ── Plugin 管理 ──────────────────────────────────────────────────────

@main.group()
def plugin():
    """插件安装与管理。"""
    pass


@plugin.command()
@click.argument("runtime", type=click.Choice(["claude"]))
@click.option("--scope", type=click.Choice(["project", "global"]), default="project",
              help="安装范围: project（当前项目）或 global（全局）")
@click.option("--project-dir", default=None, help="项目目录（默认当前目录）")
def install(runtime, scope, project_dir):
    """为 AI Runtime 安装 Memento 钩子和 MCP 配置。

    用法: memento plugin install claude [--scope project|global]
    """
    if runtime == "claude":
        _install_claude(scope, project_dir)


def _install_claude(scope: str, project_dir: str | None):
    """安装 Memento 到 Claude Code 环境（已废弃）。"""

    click.echo("⚠ 'memento plugin install claude' 已废弃，请使用 'memento setup' 代替。")
    click.echo("  memento setup 会全局安装 hooks 和 MCP，无需每个项目单独配置。")
    click.echo("  运行: memento setup\n")
    raise SystemExit(1)

    project_root = Path(project_dir) if project_dir else Path.cwd()

    # 1. 定位 hook-handler.sh
    hook_handler = _find_hook_handler()
    if not hook_handler:
        raise click.ClickException(
            "找不到 hook-handler.sh。请确保 memento 已正确安装（pip install memento）。"
        )

    # 2. 注入 Hooks 到 settings.json
    if scope == "global":
        settings_dir = Path.home() / ".claude"
    else:
        settings_dir = project_root / ".claude"

    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"

    settings = {}
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            settings = {}

    hooks = settings.setdefault("hooks", {})
    handler_path = str(hook_handler)

    memento_hooks = {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{handler_path} session-start",
                "timeout": 10,
            }],
        }],
        "PostToolUse": [{
            "matcher": "*",
            "hooks": [{
                "type": "command",
                "command": f"{handler_path} observe",
                "timeout": 5,
            }],
        }],
        "Stop": [{
            "hooks": [{
                "type": "command",
                "command": f"{handler_path} flush-and-epoch",
                "timeout": 15,
            }],
        }],
        "SessionEnd": [{
            "hooks": [{
                "type": "command",
                "command": f"{handler_path} session-end",
                "timeout": 15,
            }],
        }],
    }

    changed_hooks = []
    for event, entries in memento_hooks.items():
        existing = hooks.get(event, [])
        # 检查是否已安装（通过 hook-handler.sh 路径判断）
        already = any(
            "hook-handler.sh" in h.get("command", "")
            for entry in existing
            for h in entry.get("hooks", [])
        )
        if not already:
            hooks[event] = existing + entries
            changed_hooks.append(event)

    settings["hooks"] = hooks
    settings_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")

    # 3. 注入 MCP 配置到 .mcp.json
    mcp_file = project_root / ".mcp.json"
    mcp_config = {}
    if mcp_file.exists():
        try:
            mcp_config = json.loads(mcp_file.read_text())
        except json.JSONDecodeError:
            mcp_config = {}

    servers = mcp_config.setdefault("mcpServers", {})
    mcp_changed = False
    if "memento" not in servers:
        # 找到 memento-mcp-server 的实际路径
        mcp_cmd = shutil.which("memento-mcp-server")
        if mcp_cmd:
            servers["memento"] = {
                "type": "stdio",
                "command": mcp_cmd,
                "args": [],
            }
        else:
            # fallback: 用 python -m
            import sys
            servers["memento"] = {
                "type": "stdio",
                "command": sys.executable,
                "args": [str(Path(__file__).resolve().parent.parent.parent / "plugin" / "scripts" / "mcp-server.py")],
            }
        mcp_changed = True

    mcp_config["mcpServers"] = servers
    mcp_file.write_text(json.dumps(mcp_config, indent=2, ensure_ascii=False) + "\n")

    # 4. 输出结果
    click.echo("✅ Memento 已安装到 Claude Code 环境。")
    click.echo(f"   范围: {scope}")
    click.echo(f"   Hooks: {settings_file}")
    if changed_hooks:
        click.echo(f"   注入事件: {', '.join(changed_hooks)}")
    else:
        click.echo("   Hooks 已存在，跳过。")
    click.echo(f"   MCP: {mcp_file}")
    if mcp_changed:
        click.echo("   MCP server 已配置。")
    else:
        click.echo("   MCP server 已存在，跳过。")


def _find_hook_handler() -> Path | None:
    """查找 hook-handler.sh 的路径。"""
    # 1. 包内 package_data 路径（pip install 后可用）
    pkg_data = Path(__file__).resolve().parent / "scripts" / "hook-handler.sh"
    if pkg_data.exists():
        return pkg_data

    # 2. 开发模式：项目根 plugin/ 目录
    dev_path = Path(__file__).resolve().parent.parent.parent / "plugin" / "scripts" / "hook-handler.sh"
    if dev_path.exists():
        return dev_path

    return None


@main.command()
@click.option("--port", default=8230, help="服务端口")
@click.option("--no-open", is_flag=True, help="不自动打开浏览器")
def dashboard(port, no_open):
    """启动 Web Dashboard。"""
    try:
        from memento.dashboard.server import run_server
    except ImportError:
        import sys
        import subprocess
        click.echo("MEMENTO: 检测到未安装 Dashboard 依赖，正在自动安装 (fastapi, uvicorn, jinja2)...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi>=0.100", "uvicorn[standard]>=0.20", "jinja2"], stdout=subprocess.DEVNULL)
            from memento.dashboard.server import run_server
        except Exception as e:
            raise click.ClickException(
                f"自动安装 Dashboard 依赖失败: {e}\n请手动运行: pip install -e \".[dashboard]\" 或 pip install fastapi uvicorn jinja2"
            )
            
    run_server(port=port, open_browser=not no_open)


# ── Update 命令 ──


def _detect_install_source() -> tuple[str, str]:
    """检测当前安装方式和来源。

    使用 importlib.metadata 读取 distribution 元数据，而非猜测源码路径。

    Returns:
        (install_type, source_url)
        install_type: "editable" | "git" | "index" | "unknown"
        source_url: 检测到的安装源 URL，或空字符串
    """
    import importlib.util

    # 1. 检查 editable install：源码目录下有 .git
    spec = importlib.util.find_spec("memento")
    if spec and spec.origin:
        origin_path = Path(spec.origin).resolve()
        for parent in origin_path.parents:
            if (parent / ".git").exists():
                try:
                    import subprocess
                    result = subprocess.run(
                        ["git", "remote", "get-url", "origin"],
                        capture_output=True, text=True, cwd=str(parent),
                    )
                    if result.returncode == 0:
                        return "editable", result.stdout.strip()
                except Exception:
                    pass
                return "editable", ""

    # 2. 检查 direct_url.json（PEP 610 — pip 记录安装来源）
    try:
        from importlib.metadata import distribution
        dist = distribution("memento")
        direct_url_text = dist.read_text("direct_url.json")
        if direct_url_text:
            direct_url = json.loads(direct_url_text)
            url = direct_url.get("url", "")
            vcs_info = direct_url.get("vcs_info", {})
            if vcs_info.get("vcs") == "git":
                return "git", url
            if url:
                return "unknown", url
    except Exception:
        pass

    # 3. 无法确定来源
    return "unknown", ""


def _get_latest_tag(repo_url: str) -> str | None:
    """通过 git ls-remote 获取远程仓库的最新版本 tag（vX.Y.Z 格式）。"""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--sort=-v:refname", repo_url],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                ref = parts[1]
                if ref.startswith("refs/tags/v") and "^{}" not in ref:
                    return ref.split("/")[-1]
        return None
    except Exception:
        return None


def _compare_versions(current: str, latest: str) -> int:
    """比较两个版本号。返回: -1 (current < latest), 0 (equal), 1 (current > latest)。"""
    def parse(v: str) -> tuple:
        v = v.lstrip("v")
        parts = []
        for p in v.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(p)
        return tuple(parts)

    c, l = parse(current), parse(latest)
    if c < l:
        return -1
    if c > l:
        return 1
    return 0


@main.command()
@click.option("--check", is_flag=True, help="仅检查是否有更新，不执行安装")
@click.option("--source", default=None, help="指定 Git 仓库 URL")
@click.option("--tag", default=None, help="安装指定版本 tag（如 v0.9.0）")
@click.option("--extras", default=None, help="安装额外依赖组，逗号分隔（如 dashboard,local）")
def update(check, source, tag, extras):
    """检查并更新 Memento 到最新版本。

    从 Git 仓库获取最新 tag 并安装。支持私有仓库，无需 PyPI。

    \b
    自动检测安装来源（优先级）:
      1. --source 参数显式指定
      2. PEP 610 direct_url.json（pip 安装时记录的来源）
      3. 当前 .git remote（editable 模式）
      若均无法检测，要求用户显式 --source。

    \b
    示例:
      memento update                    # 自动检测源并更新
      memento update --check            # 仅检查
      memento update --tag v0.9.0       # 安装指定版本
      memento update --extras dashboard # 带 dashboard 依赖
      memento update --source ssh://git@example.com/repo.git
    """
    import subprocess
    import sys

    current_version = __version__

    # 1. 确定安装源
    install_type, detected_source = _detect_install_source()

    if install_type == "editable" and not source:
        click.echo(f"📦 当前安装方式: 开发模式 (editable)")
        click.echo(f"   源码目录已关联 Git，请直接使用 git pull 更新。")
        if detected_source:
            click.echo(f"   仓库: {detected_source}")
        click.echo(f"\n   git pull && pip install -e .")
        return

    repo_url = source
    if not repo_url:
        if install_type == "git" and detected_source:
            repo_url = detected_source
        else:
            raise click.ClickException(
                "无法自动检测安装来源。请使用 --source 指定 Git 仓库 URL。\n"
                "示例: memento update --source ssh://git@example.com/repo.git"
            )

    click.echo(f"📦 当前版本: {current_version}")
    click.echo(f"   更新源: {repo_url}")
    if install_type != "unknown":
        click.echo(f"   安装方式: {install_type}")

    # 2. 获取最新版本
    if tag:
        latest_tag = tag
        click.echo(f"   目标版本: {latest_tag}（手动指定）")
    else:
        click.echo("   正在检查最新版本...")
        latest_tag = _get_latest_tag(repo_url)
        if not latest_tag:
            raise click.ClickException(
                f"无法获取远程版本。请确认:\n"
                f"  1. Git 仓库可达: {repo_url}\n"
                f"  2. 仓库中存在 vX.Y.Z 格式的 tag"
            )
        click.echo(f"   最新版本: {latest_tag}")

    # 3. 比较版本
    cmp = _compare_versions(current_version, latest_tag)
    if cmp == 0:
        click.echo(f"\n✅ 已经是最新版本 ({current_version})。")
        return
    elif cmp > 0:
        click.echo(f"\n⚠️  当前版本 ({current_version}) 比远程 ({latest_tag}) 更新。")
        if not tag:
            return

    if check:
        click.echo(f"\n🔄 有新版本可用: {current_version} → {latest_tag}")
        click.echo(f"   运行 `memento update` 执行更新。")
        return

    # 4. 构建安装命令
    click.echo(f"\n🔄 正在更新: {current_version} → {latest_tag}")

    install_url = f"git+{repo_url}@{latest_tag}"
    # extras 通过 pip 标准语法：memento[dashboard,local]
    pkg_spec = "memento"
    if extras:
        # 校验 extras 格式
        extra_list = [e.strip() for e in extras.split(",") if e.strip()]
        if extra_list:
            pkg_spec = f"memento[{','.join(extra_list)}]"

    # 使用 PEP 440 direct reference: memento[extras] @ git+url@tag
    install_spec = f"{pkg_spec} @ {install_url}"

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", install_spec]
    click.echo(f"   执行: pip install --upgrade '{install_spec}'")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            click.echo(f"\n✅ 更新完成: {latest_tag}")
            click.echo("   请重新运行 memento 命令以使用新版本。")
        else:
            stderr = result.stderr.strip()
            raise click.ClickException(f"pip install 失败:\n{stderr}")
    except subprocess.TimeoutExpired:
        raise click.ClickException("更新超时（120s），请检查网络连接。")


if __name__ == "__main__":
    main()
