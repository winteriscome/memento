"""CLI 行为测试。"""

import json
import struct
from unittest.mock import patch

from click.testing import CliRunner

from memento.cli import main
from memento.core import MementoCore


def test_eval_compare_outputs_delta(tmp_path):
    """eval --compare-db 应返回主评估、对照评估和差值。"""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    queries_file = tmp_path / "queries.json"
    fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)

    with patch("memento.core.get_embedding") as mock_core_embed, patch(
        "memento.embedding.get_embedding"
    ) as mock_embedding_embed:
        mock_core_embed.return_value = (fake_blob, 4, False)
        mock_embedding_embed.return_value = (fake_blob, 4, False)

        core_a = MementoCore(db_path=db_a)
        expected_id = core_a.capture("token guideline current")
        stale_id = core_a.capture("old token guideline")
        core_a.close()

        core_b = MementoCore(db_path=db_b)
        core_b.capture("token guideline current")
        core_b.capture("old token guideline")
        core_b.close()

    queries_file.write_text(
        json.dumps(
            [
                {
                    "query": "token",
                    "expected_ids": [expected_id],
                    "stale_ids": [stale_id],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "eval",
            "--queries",
            str(queries_file),
            "--db",
            str(db_a),
            "--compare-db",
            str(db_b),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "primary" in payload
    assert "comparison" in payload
    assert "delta" in payload
    assert "summary" in payload
    assert set(payload["delta"].keys()) == {
        "precision_at_3",
        "mrr",
        "stale_hit_rate",
    }
    assert set(payload["summary"].keys()) == {
        "stale_hit_rate_reduction_ratio",
        "precision_gate_passed",
        "stale_suppression_gate_passed",
        "upgrade_recommended",
    }


def test_seed_experiment_writes_queries_file(tmp_path):
    """seed-experiment 应写入实验数据并生成查询集。"""
    db_path = tmp_path / "seed.db"
    queries_file = tmp_path / "queries.json"
    fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)

    with patch("memento.core.get_embedding") as mock_core_embed, patch(
        "memento.embedding.get_embedding"
    ) as mock_embedding_embed:
        mock_core_embed.return_value = (fake_blob, 4, False)
        mock_embedding_embed.return_value = (fake_blob, 4, False)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "seed-experiment",
                "--db",
                str(db_path),
                "--queries-output",
                str(queries_file),
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["inserted"] == 8
    assert queries_file.exists()
    queries = json.loads(queries_file.read_text(encoding="utf-8"))
    assert len(queries) == 5
    assert queries[0]["expected_ids"]


def test_setup_experiment_creates_ab_pair_and_manifest(tmp_path):
    """setup-experiment 应创建 A/B 数据库、查询集和清单。"""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    queries_file = tmp_path / "queries.json"
    manifest_file = tmp_path / "manifest.json"
    fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)

    with patch("memento.core.get_embedding") as mock_core_embed, patch(
        "memento.embedding.get_embedding"
    ) as mock_embedding_embed:
        mock_core_embed.return_value = (fake_blob, 4, False)
        mock_embedding_embed.return_value = (fake_blob, 4, False)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "setup-experiment",
                "--db-a",
                str(db_a),
                "--db-b",
                str(db_b),
                "--queries-output",
                str(queries_file),
                "--manifest-output",
                str(manifest_file),
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert db_a.exists()
    assert db_b.exists()
    assert queries_file.exists()
    assert manifest_file.exists()
    assert payload["db_a"] == str(db_a)
    assert payload["db_b"] == str(db_b)


def test_eval_writes_report_output(tmp_path):
    """eval --report-output 应写出完整 JSON 报告。"""
    db_path = tmp_path / "eval.db"
    queries_file = tmp_path / "queries.json"
    report_file = tmp_path / "report.json"
    fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)

    with patch("memento.core.get_embedding") as mock_core_embed, patch(
        "memento.embedding.get_embedding"
    ) as mock_embedding_embed:
        mock_core_embed.return_value = (fake_blob, 4, False)
        mock_embedding_embed.return_value = (fake_blob, 4, False)

        core = MementoCore(db_path=db_path)
        expected_id = core.capture("database choice postgresql")
        core.close()

    queries_file.write_text(
        json.dumps(
            [{"query": "database", "expected_ids": [expected_id]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "eval",
            "--queries",
            str(queries_file),
            "--db",
            str(db_path),
            "--report-output",
            str(report_file),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert report_file.exists()
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    assert payload["query_count"] == 1