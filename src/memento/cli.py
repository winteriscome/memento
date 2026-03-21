"""CLI 入口：基于 Click 的命令行界面。"""

import json
from pathlib import Path
import shutil

import click

from memento import __version__
from memento.core import MementoCore
from memento.export import export_memories, import_memories
from memento.seed import seed_experiment_dataset


def _get_core(db_path: str | None = None):
    """创建 MementoCore 实例。"""
    return MementoCore(db_path=Path(db_path) if db_path else None)


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
@click.option("--mode", type=click.Choice(["A", "B"], case_sensitive=False), default="A", help="检索模式: A=衰减+强化, B=纯相似度+时间基线")
@click.option("--db", "db_path", type=click.Path(), default=None, help="数据库路径（默认使用 MEMENTO_DB 或 ~/.memento/default.db）")
@click.option("--format", "fmt", default="text", help="输出格式: text|json")
def recall(query: str, max_results: int, mode: str, db_path: str | None, fmt: str):
    """检索记忆（带衰减权重）。"""
    core = _get_core(db_path)
    results = core.recall(query, max_results=max_results, mode=mode)
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
                "mode": mode.upper(),
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
