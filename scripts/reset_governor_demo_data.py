"""
Path: scripts/reset_governor_demo_data.py
說明：清除 governor 開發期間的 demo / smoke test 資料，避免污染真實治理判斷。
"""

from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.db import connection_scope


def main() -> None:
    with connection_scope() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM governor_decisions
                WHERE run_key LIKE 'test_%'
                   OR run_key LIKE 'family_adjust_test_%'
                   OR run_key LIKE 'feature_adjust_test_%'
                   OR run_key LIKE 'family_rebuild_governor_%'
                   OR run_key LIKE 'feature_rebuild_governor_%'
                RETURNING decision_id
                """
            )
            deleted_governor_decisions = len(cursor.fetchall())

            cursor.execute(
                """
                DELETE FROM family_performance_summary
                WHERE family_key = 'trend_following_v1'
                RETURNING summary_id
                """
            )
            deleted_family_rows = len(cursor.fetchall())

            cursor.execute(
                """
                DELETE FROM feature_diagnostics_summary
                WHERE feature_key = 'slope_5'
                RETURNING summary_id
                """
            )
            deleted_feature_rows = len(cursor.fetchall())

            cursor.execute(
                """
                DELETE FROM search_space_config
                WHERE created_by IN (
                    'repo_smoke_test',
                    'governor_bootstrap',
                    'governor_family_adjust',
                    'governor_family_feature_adjust'
                )
                RETURNING config_id
                """
            )
            deleted_search_space_rows = len(cursor.fetchall())

    print(
        json.dumps(
            {
                "deleted_governor_decisions": deleted_governor_decisions,
                "deleted_family_rows": deleted_family_rows,
                "deleted_feature_rows": deleted_feature_rows,
                "deleted_search_space_rows": deleted_search_space_rows,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()