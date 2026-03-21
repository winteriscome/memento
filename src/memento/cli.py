"""CLI 入口：基于 Click 的命令行界面。"""

import json
import sys

import click

from memento import __version__
from memento.core import MementoCore
from memento.export import export_memories, import_memories


def _get_core():
    """创建 MementoCore 实例。"""
    return MementoCore()


@click.group()
@click.version_option(__version__, prog_name="memento")
def main():
    """Memento — AI Agent 的长期记忆引擎。"""
    pass


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
    core = _get_core()
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    engram_id = core.capture(content, type=type_, importance=importance, tags=tag_list, origin=origin)
    core.close()

    click.echo(f"✅ 记忆已捕获。")
    click.echo(f"   ID: {engram_id}")


@main.command()
@click.argument("query")
@click.option("--max", "max_results", default=5, help="最大返回数量")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def recall(query: str, max_results: int, fmt: str):
    """检索记忆（带衰减权重）。"""
    core = _get_core()
    results = core.recall(query, max_results=max_results)
    core.close()

    if not results:
        click.echo("未找到相关记忆。")
        return

    if fmt == "json":
        data = []
        for r in results:
            d = {
                "id": r.id,
                "content": r.content,
                "type": r.type,
                "tags": r.tags,
                "strength": r.strength,
                "score": r.score,
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
@click.argument("engram_id")
def verify(engram_id: str):
    """人类确认某条 Agent 记忆为可信。"""
    core = _get_core()
    ok = core.verify(engram_id)
    core.close()

    if ok:
        click.echo(f"✅ 记忆 {engram_id} 已标记为已验证。")
    else:
        click.echo(f"⚠️  未找到未验证的记忆 {engram_id}。")


@main.command()
@click.argument("engram_id")
def forget(engram_id: str):
    """标记一条记忆为遗忘。"""
    core = _get_core()
    ok = core.forget(engram_id)
    core.close()

    if ok:
        click.echo(f"✅ 记忆 {engram_id} 已遗忘。")
    else:
        click.echo(f"⚠️  未找到活跃记忆 {engram_id}。")


@main.command()
def status():
    """显示数据库统计信息。"""
    core = _get_core()
    stats = core.status()
    core.close()

    click.echo("\n📊 Memento 状态")
    click.echo(f"{'─' * 40}")
    click.echo(f"  总记忆数:         {stats['total'] or 0}")
    click.echo(f"  活跃:             {stats['active'] or 0}")
    click.echo(f"  已遗忘:           {stats['forgotten'] or 0}")
    click.echo(f"  Agent 未验证:     {stats['unverified_agent'] or 0}")
    click.echo(f"  已生成 Embedding: {stats['with_embedding'] or 0}")
    click.echo(f"  Embedding 待补填: {stats['pending_embedding'] or 0}")
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


if __name__ == "__main__":
    main()
