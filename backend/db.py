# -*- coding: utf-8 -*-
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

CLIMATE_TOPIC = "farm/tray_1/sensors/climate"
WATER_TOPIC = "farm/tray_1/sensors/water"
CROPS_DATA_DIR = BASE_DIR / "crops_data"
AGROTECH_NORM_KEYS = (
    "air_temp",
    "humidity",
    "water_temp",
    "ph",
    "ec",
    "light_hours",
    "light_intensity",
)
NON_CROP_CARD_FILES = {"crops_index.md", "project_recommendations.md"}
DEFAULT_TRAY_ID = "tray_1"


class CropNotFoundError(ValueError):
    pass


class ActiveCardRevisionNotFoundError(ValueError):
    pass


class ActiveGrowingCycleExistsError(ValueError):
    pass


class NoActiveGrowingCycleError(ValueError):
    pass


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "Не задана переменная окружения DATABASE_URL. "
            "Создайте базу PostgreSQL neirognom и добавьте DATABASE_URL в .env, например: "
            "postgresql://postgres:password@localhost:5432/neirognom"
        )
    return database_url


def get_connection():
    return psycopg.connect(get_database_url(), row_factory=dict_row)


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND column_name = %s
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def get_column_data_type(cursor, table_name: str, column_name: str) -> str | None:
    cursor.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND column_name = %s
        """,
        (table_name, column_name),
    )
    row = cursor.fetchone()
    return str(row["data_type"]) if row else None


def ensure_jsonb_column(cursor, table_name: str, column_name: str) -> None:
    if get_column_data_type(cursor, table_name, column_name) == "jsonb":
        return

    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION pg_temp.safe_jsonb(value text)
        RETURNS jsonb
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN value::jsonb;
        EXCEPTION WHEN others THEN
            RETURN to_jsonb(value);
        END;
        $$;
        """
    )
    cursor.execute(
        sql.SQL("ALTER TABLE {} ALTER COLUMN {} TYPE JSONB USING pg_temp.safe_jsonb({}::text)").format(
            sql.Identifier(table_name),
            sql.Identifier(column_name),
            sql.Identifier(column_name),
        )
    )


DEVICE_FK_CONSTRAINTS = (
    ("telemetry_raw", "fk_telemetry_raw_tray_id_devices", "tray_id", "devices", "id"),
    ("telemetry_hourly", "fk_telemetry_hourly_tray_id_devices", "tray_id", "devices", "id"),
    ("anomaly_events", "fk_anomaly_events_tray_id_devices", "tray_id", "devices", "id"),
)


def normalize_device_id(device_id: Any) -> str | None:
    if device_id is None:
        return None
    normalized = str(device_id).strip()
    return normalized or None


def _ensure_device(cursor, device_id: Any, status: str | None = None) -> str | None:
    normalized_device_id = normalize_device_id(device_id)
    if normalized_device_id is None:
        return None

    cursor.execute(
        """
        INSERT INTO devices (id, status, last_seen)
        VALUES (%s, %s, now())
        ON CONFLICT (id) DO UPDATE SET
            status = COALESCE(EXCLUDED.status, devices.status),
            last_seen = EXCLUDED.last_seen
        """,
        (normalized_device_id, status),
    )
    return normalized_device_id


def ensure_device(device_id: Any) -> str | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            return _ensure_device(cursor, device_id)


def backfill_devices_for_existing_tray_ids(cursor) -> None:
    for table_name in ("telemetry_raw", "telemetry_hourly", "anomaly_events"):
        cursor.execute(
            sql.SQL(
                """
                UPDATE {}
                SET tray_id = NULL
                WHERE tray_id IS NOT NULL
                  AND btrim(tray_id) = ''
                """
            ).format(sql.Identifier(table_name))
        )

    cursor.execute(
        """
        INSERT INTO devices (id, status, last_seen)
        SELECT tray_id, NULL, now()
        FROM (
            SELECT DISTINCT tray_id FROM telemetry_raw WHERE tray_id IS NOT NULL
            UNION
            SELECT DISTINCT tray_id FROM telemetry_hourly WHERE tray_id IS NOT NULL
            UNION
            SELECT DISTINCT tray_id FROM anomaly_events WHERE tray_id IS NOT NULL
        ) AS existing_tray_ids
        ON CONFLICT (id) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO devices (id, status, last_seen)
        SELECT 'unknown', NULL, now()
        WHERE EXISTS (SELECT 1 FROM telemetry_raw WHERE tray_id IS NULL)
        ON CONFLICT (id) DO NOTHING
        """
    )


def constraint_exists(cursor, table_name: str, constraint_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND constraint_name = %s
        """,
        (table_name, constraint_name),
    )
    return cursor.fetchone() is not None


def foreign_key_exists(
    cursor,
    table_name: str,
    column_name: str,
    referenced_table: str,
    referenced_column: str,
) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class child_table ON child_table.oid = c.conrelid
        JOIN pg_namespace child_namespace ON child_namespace.oid = child_table.relnamespace
        JOIN pg_class parent_table ON parent_table.oid = c.confrelid
        JOIN pg_attribute child_column
          ON child_column.attrelid = c.conrelid
         AND child_column.attnum = ANY(c.conkey)
        JOIN pg_attribute parent_column
          ON parent_column.attrelid = c.confrelid
         AND parent_column.attnum = ANY(c.confkey)
        WHERE c.contype = 'f'
          AND child_namespace.nspname = current_schema()
          AND child_table.relname = %s
          AND child_column.attname = %s
          AND parent_table.relname = %s
          AND parent_column.attname = %s
        LIMIT 1
        """,
        (table_name, column_name, referenced_table, referenced_column),
    )
    return cursor.fetchone() is not None


def add_foreign_key_if_missing(
    cursor,
    table_name: str,
    constraint_name: str,
    column_name: str,
    referenced_table: str,
    referenced_column: str,
) -> None:
    if constraint_exists(cursor, table_name, constraint_name) or foreign_key_exists(
        cursor,
        table_name,
        column_name,
        referenced_table,
        referenced_column,
    ):
        return

    cursor.execute(
        sql.SQL(
            """
            ALTER TABLE {}
            ADD CONSTRAINT {}
            FOREIGN KEY ({})
            REFERENCES {}({})
            """
        ).format(
            sql.Identifier(table_name),
            sql.Identifier(constraint_name),
            sql.Identifier(column_name),
            sql.Identifier(referenced_table),
            sql.Identifier(referenced_column),
        )
    )


def ensure_device_foreign_keys(cursor) -> None:
    backfill_devices_for_existing_tray_ids(cursor)
    for fk_config in DEVICE_FK_CONSTRAINTS:
        add_foreign_key_if_missing(cursor, *fk_config)


def extract_markdown_section(content: str, heading: str) -> str | None:
    match = re.search(
        rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        content,
    )
    if not match:
        return None
    return match.group("body").strip()


def extract_first_nonempty_line(content: str, heading: str) -> str | None:
    section = extract_markdown_section(content, heading)
    if not section:
        return None
    for line in section.splitlines():
        value = line.strip()
        if value:
            return value
    return None


def extract_crop_slug(content: str, fallback_slug: str) -> str:
    match = re.search(r"(?im)^#\s*CULTURE:\s*([a-z0-9_-]+)\s*$", content)
    return match.group(1).strip().lower() if match else fallback_slug


def extract_card_title(content: str, fallback_slug: str) -> str:
    name_ru = extract_first_nonempty_line(content, "Название")
    if name_ru:
        return name_ru

    match = re.search(r"(?m)^#\s+(.+?)\s*$", content)
    if match:
        return match.group(1).strip()

    return fallback_slug.replace("_", " ").title()


def parse_norm_value(raw_value: str) -> Any:
    value = raw_value.strip()
    numeric_range_match = re.fullmatch(
        r"(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)",
        value,
    )
    if numeric_range_match:
        low, high = numeric_range_match.groups()
        return {"min": float(low), "max": float(high)}

    numeric_match = re.fullmatch(r"-?\d+(?:\.\d+)?", value)
    if numeric_match:
        return float(value)

    object_match = re.fullmatch(r'([a-zA-Z_][\w-]*)\s*:\s*"?(.*?)"?', value)
    if object_match:
        key, nested_value = object_match.groups()
        return {key: nested_value}

    return value.strip('"')


def parse_agrotech_params(content: str) -> dict[str, Any]:
    norms_block = extract_markdown_section(content, "Нормы")
    if not norms_block:
        return {}

    params: dict[str, Any] = {}
    for key in AGROTECH_NORM_KEYS:
        match = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", norms_block)
        if match:
            params[key] = parse_norm_value(match.group(1))
    return params


def ensure_agrotech_schema(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS crops (
            id BIGSERIAL PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name_ru TEXT,
            crop_type TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agrotech_cards (
            id BIGSERIAL PRIMARY KEY,
            crop_id BIGINT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agrotech_card_revisions (
            id BIGSERIAL PRIMARY KEY,
            card_id BIGINT NOT NULL,
            version_major INTEGER NOT NULL,
            version_minor INTEGER NOT NULL,
            version_label TEXT NOT NULL,
            parent_revision_id BIGINT,
            params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            content TEXT NOT NULL,
            source TEXT,
            change_reason TEXT,
            created_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_active BOOLEAN NOT NULL DEFAULT false
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agrotech_audit_log (
            id BIGSERIAL PRIMARY KEY,
            card_id BIGINT NOT NULL,
            revision_id BIGINT,
            action TEXT NOT NULL,
            old_params_json JSONB,
            new_params_json JSONB,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agrotech_cards_crop_id ON agrotech_cards(crop_id)"
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agrotech_card_revisions_version
        ON agrotech_card_revisions(card_id, version_major, version_minor)
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agrotech_card_revisions_active
        ON agrotech_card_revisions(card_id)
        WHERE is_active
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_agrotech_audit_log_card_id ON agrotech_audit_log(card_id, created_at DESC)"
    )
    add_foreign_key_if_missing(
        cursor,
        "agrotech_cards",
        "fk_agrotech_cards_crop_id_crops",
        "crop_id",
        "crops",
        "id",
    )
    add_foreign_key_if_missing(
        cursor,
        "agrotech_card_revisions",
        "fk_agrotech_card_revisions_card_id_cards",
        "card_id",
        "agrotech_cards",
        "id",
    )
    add_foreign_key_if_missing(
        cursor,
        "agrotech_card_revisions",
        "fk_agrotech_card_revisions_parent_revision_id",
        "parent_revision_id",
        "agrotech_card_revisions",
        "id",
    )
    add_foreign_key_if_missing(
        cursor,
        "agrotech_audit_log",
        "fk_agrotech_audit_log_card_id_cards",
        "card_id",
        "agrotech_cards",
        "id",
    )
    add_foreign_key_if_missing(
        cursor,
        "agrotech_audit_log",
        "fk_agrotech_audit_log_revision_id_revisions",
        "revision_id",
        "agrotech_card_revisions",
        "id",
    )


def _get_or_create_crop(
    cursor,
    *,
    slug: str,
    name_ru: str | None = None,
    crop_type: str | None = None,
) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO crops (slug, name_ru, crop_type)
        VALUES (%s, %s, %s)
        ON CONFLICT (slug) DO NOTHING
        RETURNING id, slug, name_ru, crop_type, created_at
        """,
        (slug, name_ru, crop_type),
    )
    row = cursor.fetchone()
    if row:
        return row

    cursor.execute(
        """
        SELECT id, slug, name_ru, crop_type, created_at
        FROM crops
        WHERE slug = %s
        """,
        (slug,),
    )
    return cursor.fetchone()


def get_or_create_crop(
    *,
    slug: str,
    name_ru: str | None = None,
    crop_type: str | None = None,
) -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            return _get_or_create_crop(
                cursor,
                slug=slug,
                name_ru=name_ru,
                crop_type=crop_type,
            )


def _get_or_create_agrotech_card(cursor, *, crop_id: int, title: str) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO agrotech_cards (crop_id, title, status)
        VALUES (%s, %s, 'active')
        ON CONFLICT (crop_id) DO NOTHING
        RETURNING id, crop_id, title, status, created_at
        """,
        (crop_id, title),
    )
    row = cursor.fetchone()
    if row:
        return row

    cursor.execute(
        """
        SELECT id, crop_id, title, status, created_at
        FROM agrotech_cards
        WHERE crop_id = %s
        """,
        (crop_id,),
    )
    return cursor.fetchone()


def _create_card_revision(
    cursor,
    *,
    card_id: int,
    version_major: int,
    version_minor: int,
    params_json: dict[str, Any] | None,
    content: str,
    source: str | None = None,
    change_reason: str | None = None,
    created_by: str | None = None,
    parent_revision_id: int | None = None,
    is_active: bool = True,
) -> dict[str, Any] | None:
    version_label = f"v{version_major}.{version_minor}"
    cursor.execute(
        """
        SELECT id, card_id, version_major, version_minor, version_label,
               parent_revision_id, params_json, content, source,
               change_reason, created_by, created_at, is_active
        FROM agrotech_card_revisions
        WHERE card_id = %s
          AND version_major = %s
          AND version_minor = %s
        """,
        (card_id, version_major, version_minor),
    )
    existing_revision = cursor.fetchone()
    if existing_revision:
        return existing_revision

    if is_active:
        cursor.execute(
            """
            UPDATE agrotech_card_revisions
            SET is_active = false
            WHERE card_id = %s
              AND is_active
            """,
            (card_id,),
        )

    cursor.execute(
        """
        INSERT INTO agrotech_card_revisions (
            card_id, version_major, version_minor, version_label,
            parent_revision_id, params_json, content, source,
            change_reason, created_by, is_active
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, card_id, version_major, version_minor, version_label,
                  parent_revision_id, params_json, content, source,
                  change_reason, created_by, created_at, is_active
        """,
        (
            card_id,
            version_major,
            version_minor,
            version_label,
            parent_revision_id,
            Jsonb(params_json or {}),
            content,
            source,
            change_reason,
            created_by,
            is_active,
        ),
    )
    revision = cursor.fetchone()
    cursor.execute(
        """
        INSERT INTO agrotech_audit_log (
            card_id, revision_id, action, old_params_json,
            new_params_json, reason, created_at
        )
        VALUES (%s, %s, %s, NULL, %s, %s, now())
        """,
        (
            card_id,
            revision["id"],
            "create_revision",
            Jsonb(params_json or {}),
            change_reason,
        ),
    )
    return revision


def _card_has_active_revision(cursor, card_id: int) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM agrotech_card_revisions
        WHERE card_id = %s
          AND is_active
        LIMIT 1
        """,
        (card_id,),
    )
    return cursor.fetchone() is not None


def _card_revision_exists(
    cursor,
    *,
    card_id: int,
    version_major: int,
    version_minor: int,
) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM agrotech_card_revisions
        WHERE card_id = %s
          AND version_major = %s
          AND version_minor = %s
        LIMIT 1
        """,
        (card_id, version_major, version_minor),
    )
    return cursor.fetchone() is not None


def create_card_revision(
    *,
    card_id: int,
    version_major: int,
    version_minor: int,
    params_json: dict[str, Any] | None,
    content: str,
    source: str | None = None,
    change_reason: str | None = None,
    created_by: str | None = None,
    parent_revision_id: int | None = None,
    is_active: bool = True,
) -> dict[str, Any] | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            return _create_card_revision(
                cursor,
                card_id=card_id,
                version_major=version_major,
                version_minor=version_minor,
                params_json=params_json,
                content=content,
                source=source,
                change_reason=change_reason,
                created_by=created_by,
                parent_revision_id=parent_revision_id,
                is_active=is_active,
            )


def _import_crop_cards_from_md(cursor) -> int:
    if not CROPS_DATA_DIR.exists():
        return 0

    imported_count = 0
    for path in sorted(CROPS_DATA_DIR.glob("*.md")):
        if path.name in NON_CROP_CARD_FILES:
            continue

        content = path.read_text(encoding="utf-8")
        slug = extract_crop_slug(content, path.stem)
        title = extract_card_title(content, slug)
        crop_type = extract_first_nonempty_line(content, "Тип культуры")
        params_json = parse_agrotech_params(content)

        crop = _get_or_create_crop(
            cursor,
            slug=slug,
            name_ru=title,
            crop_type=crop_type,
        )
        card = _get_or_create_agrotech_card(cursor, crop_id=crop["id"], title=title)
        if _card_revision_exists(
            cursor,
            card_id=card["id"],
            version_major=1,
            version_minor=0,
        ):
            continue

        revision = _create_card_revision(
            cursor,
            card_id=card["id"],
            version_major=1,
            version_minor=0,
            params_json=params_json,
            content=content,
            source=f"crops_data/{path.name}",
            change_reason="Initial import from Markdown",
            created_by="init_db",
            is_active=not _card_has_active_revision(cursor, card["id"]),
        )
        if revision and revision.get("version_major") == 1 and revision.get("version_minor") == 0:
            imported_count += 1

    return imported_count


def import_crop_cards_from_md() -> int:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            return _import_crop_cards_from_md(cursor)


def _get_active_card_revision(cursor, crop_slug: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT
            crops.id AS crop_id,
            crops.slug,
            crops.name_ru,
            crops.crop_type,
            agrotech_cards.id AS card_id,
            agrotech_cards.title,
            agrotech_cards.status,
            agrotech_card_revisions.id AS revision_id,
            agrotech_card_revisions.version_major,
            agrotech_card_revisions.version_minor,
            agrotech_card_revisions.version_label,
            agrotech_card_revisions.parent_revision_id,
            agrotech_card_revisions.params_json,
            agrotech_card_revisions.content,
            agrotech_card_revisions.source,
            agrotech_card_revisions.change_reason,
            agrotech_card_revisions.created_by,
            agrotech_card_revisions.created_at,
            agrotech_card_revisions.is_active
        FROM crops
        JOIN agrotech_cards ON agrotech_cards.crop_id = crops.id
        JOIN agrotech_card_revisions
          ON agrotech_card_revisions.card_id = agrotech_cards.id
        WHERE crops.slug = %s
          AND agrotech_card_revisions.is_active
        LIMIT 1
        """,
        (crop_slug,),
    )
    return cursor.fetchone()


def get_active_card_revision(crop_slug: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            return _get_active_card_revision(cursor, crop_slug)


def ensure_growing_cycles_schema(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS growing_cycles (
            id BIGSERIAL PRIMARY KEY,
            tray_id TEXT NOT NULL,
            crop_id BIGINT NOT NULL,
            card_revision_id BIGINT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    if not constraint_exists(cursor, "growing_cycles", "chk_growing_cycles_status"):
        cursor.execute(
            """
            ALTER TABLE growing_cycles
            ADD CONSTRAINT chk_growing_cycles_status
            CHECK (status IN ('active', 'finished', 'cancelled'))
            """
        )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_growing_cycles_active_tray_id
        ON growing_cycles(tray_id)
        WHERE status = 'active'
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_growing_cycles_tray_status
        ON growing_cycles(tray_id, status, started_at DESC)
        """
    )
    add_foreign_key_if_missing(
        cursor,
        "growing_cycles",
        "fk_growing_cycles_tray_id_devices",
        "tray_id",
        "devices",
        "id",
    )
    add_foreign_key_if_missing(
        cursor,
        "growing_cycles",
        "fk_growing_cycles_crop_id_crops",
        "crop_id",
        "crops",
        "id",
    )
    add_foreign_key_if_missing(
        cursor,
        "growing_cycles",
        "fk_growing_cycles_card_revision_id_revisions",
        "card_revision_id",
        "agrotech_card_revisions",
        "id",
    )


def calculate_cycle_day_number(
    started_at: datetime | None,
    finished_at: datetime | None,
    status: str | None,
) -> int | None:
    if started_at is None:
        return None

    if status == "finished" and finished_at is not None:
        end_at = finished_at
    else:
        end_at = datetime.now(started_at.tzinfo)

    return max((end_at.date() - started_at.date()).days + 1, 1)


def row_to_growing_cycle(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "tray_id": row["tray_id"],
        "status": row["status"],
        "crop_slug": row["crop_slug"],
        "crop_name_ru": row["crop_name_ru"],
        "card_revision_id": row["card_revision_id"],
        "version_label": row["version_label"],
        "started_at": format_timestamp(row["started_at"]),
        "finished_at": format_timestamp(row["finished_at"]) if row["finished_at"] is not None else None,
        "day_number": calculate_cycle_day_number(
            row["started_at"],
            row["finished_at"],
            row["status"],
        ),
    }


def _select_growing_cycle_by_id(cursor, cycle_id: int) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT
            growing_cycles.id,
            growing_cycles.tray_id,
            growing_cycles.status,
            growing_cycles.card_revision_id,
            growing_cycles.started_at,
            growing_cycles.finished_at,
            crops.slug AS crop_slug,
            crops.name_ru AS crop_name_ru,
            agrotech_card_revisions.version_label
        FROM growing_cycles
        JOIN crops ON crops.id = growing_cycles.crop_id
        JOIN agrotech_card_revisions
          ON agrotech_card_revisions.id = growing_cycles.card_revision_id
        WHERE growing_cycles.id = %s
        """,
        (cycle_id,),
    )
    return cursor.fetchone()


def _get_current_growing_cycle(cursor, tray_id: str = DEFAULT_TRAY_ID) -> dict[str, Any] | None:
    normalized_tray_id = normalize_device_id(tray_id) or DEFAULT_TRAY_ID
    cursor.execute(
        """
        SELECT
            growing_cycles.id,
            growing_cycles.tray_id,
            growing_cycles.status,
            growing_cycles.card_revision_id,
            growing_cycles.started_at,
            growing_cycles.finished_at,
            crops.slug AS crop_slug,
            crops.name_ru AS crop_name_ru,
            agrotech_card_revisions.version_label
        FROM growing_cycles
        JOIN crops ON crops.id = growing_cycles.crop_id
        JOIN agrotech_card_revisions
          ON agrotech_card_revisions.id = growing_cycles.card_revision_id
        WHERE growing_cycles.tray_id = %s
          AND growing_cycles.status = 'active'
        ORDER BY growing_cycles.started_at DESC, growing_cycles.id DESC
        LIMIT 1
        """,
        (normalized_tray_id,),
    )
    return cursor.fetchone()


def get_available_crops() -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    crops.id,
                    crops.slug,
                    crops.name_ru,
                    crops.crop_type,
                    agrotech_cards.id AS card_id,
                    agrotech_card_revisions.id AS active_revision_id,
                    agrotech_card_revisions.version_label
                FROM crops
                JOIN agrotech_cards ON agrotech_cards.crop_id = crops.id
                JOIN agrotech_card_revisions
                  ON agrotech_card_revisions.card_id = agrotech_cards.id
                 AND agrotech_card_revisions.is_active
                ORDER BY crops.slug
                """
            )
            return cursor.fetchall()


def get_current_growing_cycle(tray_id: str = DEFAULT_TRAY_ID) -> dict[str, Any] | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            return row_to_growing_cycle(_get_current_growing_cycle(cursor, tray_id))


def start_growing_cycle(
    crop_slug: str,
    tray_id: str = DEFAULT_TRAY_ID,
    notes: str | None = None,
) -> dict[str, Any]:
    normalized_tray_id = normalize_device_id(tray_id) or DEFAULT_TRAY_ID
    normalized_crop_slug = str(crop_slug or "").strip()
    if not normalized_crop_slug:
        raise CropNotFoundError("crop_slug is required")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_device(cursor, normalized_tray_id)

            cursor.execute(
                """
                SELECT id
                FROM crops
                WHERE slug = %s
                """,
                (normalized_crop_slug,),
            )
            crop = cursor.fetchone()
            if crop is None:
                raise CropNotFoundError(f"Crop '{normalized_crop_slug}' not found")

            active_revision = _get_active_card_revision(cursor, normalized_crop_slug)
            if active_revision is None:
                raise ActiveCardRevisionNotFoundError(
                    f"Active agrotech card revision for crop '{normalized_crop_slug}' not found"
                )

            if _get_current_growing_cycle(cursor, normalized_tray_id) is not None:
                raise ActiveGrowingCycleExistsError(
                    f"Tray '{normalized_tray_id}' already has an active growing cycle"
                )

            try:
                cursor.execute(
                    """
                    INSERT INTO growing_cycles (
                        tray_id, crop_id, card_revision_id, status,
                        started_at, notes, created_at
                    )
                    VALUES (%s, %s, %s, 'active', now(), %s, now())
                    RETURNING id
                    """,
                    (
                        normalized_tray_id,
                        active_revision["crop_id"],
                        active_revision["revision_id"],
                        notes,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ActiveGrowingCycleExistsError(
                    f"Tray '{normalized_tray_id}' already has an active growing cycle"
                ) from exc

            created = cursor.fetchone()
            cycle = _select_growing_cycle_by_id(cursor, created["id"])
            return row_to_growing_cycle(cycle)


def finish_growing_cycle(
    tray_id: str = DEFAULT_TRAY_ID,
    notes: str | None = None,
) -> dict[str, Any]:
    normalized_tray_id = normalize_device_id(tray_id) or DEFAULT_TRAY_ID

    with get_connection() as connection:
        with connection.cursor() as cursor:
            active_cycle = _get_current_growing_cycle(cursor, normalized_tray_id)
            if active_cycle is None:
                raise NoActiveGrowingCycleError(
                    f"Tray '{normalized_tray_id}' has no active growing cycle"
                )

            cursor.execute(
                """
                UPDATE growing_cycles
                SET status = 'finished',
                    finished_at = now(),
                    notes = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id
                """,
                (notes, active_cycle["id"]),
            )
            updated = cursor.fetchone()
            cycle = _select_growing_cycle_by_id(cursor, updated["id"])
            return row_to_growing_cycle(cycle)


def init_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    status TEXT,
                    last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS status TEXT")
            cursor.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ")
            cursor.execute("UPDATE devices SET last_seen = now() WHERE last_seen IS NULL")
            cursor.execute("ALTER TABLE devices ALTER COLUMN last_seen SET DEFAULT now()")
            cursor.execute("ALTER TABLE devices ALTER COLUMN last_seen SET NOT NULL")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_raw (
                    id BIGSERIAL PRIMARY KEY,
                    topic TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    tray_id TEXT,
                    sensor_type TEXT,
                    air_temp DOUBLE PRECISION,
                    humidity DOUBLE PRECISION,
                    water_temp DOUBLE PRECISION,
                    ph DOUBLE PRECISION,
                    ec DOUBLE PRECISION,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(
                "ALTER TABLE telemetry_raw ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ"
            )
            if column_exists(cursor, "telemetry_raw", "created_at"):
                cursor.execute(
                    "UPDATE telemetry_raw SET recorded_at = created_at WHERE recorded_at IS NULL"
                )
            cursor.execute(
                "UPDATE telemetry_raw SET recorded_at = now() WHERE recorded_at IS NULL"
            )
            cursor.execute(
                "ALTER TABLE telemetry_raw ALTER COLUMN recorded_at SET DEFAULT now()"
            )
            cursor.execute(
                "ALTER TABLE telemetry_raw ALTER COLUMN recorded_at SET NOT NULL"
            )
            ensure_jsonb_column(cursor, "telemetry_raw", "payload")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_raw_recorded_at ON telemetry_raw(recorded_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_raw_topic_id ON telemetry_raw(topic, id DESC)"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_hourly (
                    id BIGSERIAL PRIMARY KEY,
                    tray_id TEXT,
                    sensor_type TEXT,
                    hour_start TIMESTAMPTZ NOT NULL,
                    air_temp DOUBLE PRECISION,
                    humidity DOUBLE PRECISION,
                    water_temp DOUBLE PRECISION,
                    ph DOUBLE PRECISION,
                    ec DOUBLE PRECISION,
                    air_temp_avg DOUBLE PRECISION,
                    air_temp_min DOUBLE PRECISION,
                    air_temp_max DOUBLE PRECISION,
                    air_temp_count INTEGER NOT NULL DEFAULT 0,
                    humidity_avg DOUBLE PRECISION,
                    humidity_min DOUBLE PRECISION,
                    humidity_max DOUBLE PRECISION,
                    humidity_count INTEGER NOT NULL DEFAULT 0,
                    water_temp_avg DOUBLE PRECISION,
                    water_temp_min DOUBLE PRECISION,
                    water_temp_max DOUBLE PRECISION,
                    water_temp_count INTEGER NOT NULL DEFAULT 0,
                    ph_avg DOUBLE PRECISION,
                    ph_min DOUBLE PRECISION,
                    ph_max DOUBLE PRECISION,
                    ph_count INTEGER NOT NULL DEFAULT 0,
                    ec_avg DOUBLE PRECISION,
                    ec_min DOUBLE PRECISION,
                    ec_max DOUBLE PRECISION,
                    ec_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for metric_name in ("air_temp", "humidity", "water_temp", "ph", "ec"):
                cursor.execute(
                    f"ALTER TABLE telemetry_hourly ADD COLUMN IF NOT EXISTS {metric_name}_avg DOUBLE PRECISION"
                )
                cursor.execute(
                    f"ALTER TABLE telemetry_hourly ADD COLUMN IF NOT EXISTS {metric_name}_min DOUBLE PRECISION"
                )
                cursor.execute(
                    f"ALTER TABLE telemetry_hourly ADD COLUMN IF NOT EXISTS {metric_name}_max DOUBLE PRECISION"
                )
                cursor.execute(
                    f"ALTER TABLE telemetry_hourly ADD COLUMN IF NOT EXISTS {metric_name}_count INTEGER NOT NULL DEFAULT 0"
                )
            cursor.execute(
                "ALTER TABLE telemetry_hourly ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            )
            cursor.execute(
                "UPDATE telemetry_hourly SET sensor_type = 'mixed' WHERE sensor_type IS NULL"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_hourly_hour_start ON telemetry_hourly(hour_start)"
            )
            cursor.execute(
                """
                DROP INDEX IF EXISTS idx_telemetry_hourly_tray_hour
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_telemetry_hourly_tray_sensor_hour
                ON telemetry_hourly(tray_id, sensor_type, hour_start)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS anomaly_events (
                    id BIGSERIAL PRIMARY KEY,
                    tray_id TEXT,
                    sensor_type TEXT,
                    event_type TEXT,
                    metric_name TEXT,
                    severity TEXT,
                    value DOUBLE PRECISION,
                    message TEXT,
                    payload JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(
                "ALTER TABLE anomaly_events ADD COLUMN IF NOT EXISTS metric_name TEXT"
            )
            cursor.execute(
                "ALTER TABLE anomaly_events ADD COLUMN IF NOT EXISTS value DOUBLE PRECISION"
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_anomaly_events_recent
                ON anomaly_events(tray_id, event_type, metric_name, created_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS advisor_reports (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    payload JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_logs (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
                    thought TEXT,
                    commands_json JSONB
                )
                """
            )
            ensure_jsonb_column(cursor, "ai_logs", "commands_json")
            ensure_device_foreign_keys(cursor)
            ensure_agrotech_schema(cursor)
            _import_crop_cards_from_md(cursor)
            ensure_growing_cycles_schema(cursor)


def parse_json_value(payload: Any) -> Any:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
    return payload


def parse_json_payload(payload: Any) -> dict[str, Any] | None:
    parsed = parse_json_value(payload)
    return parsed if isinstance(parsed, dict) else None


def json_value_to_api_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def parse_topic(topic: str) -> tuple[str | None, str | None]:
    parts = topic.split("/")
    tray_id = parts[1] if len(parts) > 1 else None
    sensor_type = None
    if "sensors" in parts:
        sensor_index = parts.index("sensors")
        if len(parts) > sensor_index + 1:
            sensor_type = parts[sensor_index + 1]
    return tray_id, sensor_type


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value) if value is not None else ""


def update_device_status(device_id: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_device(cursor, device_id, "online")


def save_telemetry(topic: str, payload: str, recorded_at: datetime | None = None) -> None:
    parsed_value = parse_json_value(payload)
    parsed_payload = parsed_value if isinstance(parsed_value, dict) else {}
    tray_id, sensor_type = parse_topic(topic)
    tray_id = normalize_device_id(tray_id)
    timestamp_sql = "%s" if recorded_at is not None else "now()"
    params: list[Any] = [
        topic,
        Jsonb(parsed_value),
        tray_id,
        sensor_type,
        number_or_none(parsed_payload.get("air_temp")),
        number_or_none(parsed_payload.get("humidity")),
        number_or_none(parsed_payload.get("water_temp")),
        number_or_none(parsed_payload.get("ph", parsed_payload.get("pH"))),
        number_or_none(parsed_payload.get("ec", parsed_payload.get("EC"))),
    ]
    if recorded_at is not None:
        params.append(recorded_at)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_device(cursor, tray_id or "unknown")
            cursor.execute(
                f"""
                INSERT INTO telemetry_raw (
                    topic, payload, tray_id, sensor_type,
                    air_temp, humidity, water_temp, ph, ec, recorded_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, {timestamp_sql})
                """,
                params,
            )


def save_ai_log(thought: str, commands: Any) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ai_logs (timestamp, thought, commands_json)
                VALUES (now(), %s, %s)
                """,
                (thought, Jsonb(commands)),
            )


def row_to_telemetry_record(row: dict[str, Any]) -> dict[str, Any]:
    payload = row["payload"]
    payload_string = json_value_to_api_string(payload)
    record = {
        "id": row["id"],
        "topic": row["topic"],
        "payload": payload_string,
        "timestamp": format_timestamp(row["recorded_at"]),
    }
    record["parsed_payload"] = parse_json_payload(payload)
    return record


def get_recent_telemetry(limit: int = 15) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, topic, payload, recorded_at
                FROM telemetry_raw
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()

    return [row_to_telemetry_record(row) for row in reversed(rows)]


def get_last_climate_records(limit: int = 3) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, topic, payload, recorded_at
                FROM telemetry_raw
                WHERE topic = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (CLIMATE_TOPIC, limit),
            )
            rows = cursor.fetchall()

    records: list[dict[str, Any]] = []
    for row in reversed(rows):
        record = row_to_telemetry_record(row)
        if isinstance(record.get("parsed_payload"), dict):
            records.append(record)
    return records


def get_recent_ai_logs(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, timestamp, thought, commands_json
                FROM ai_logs
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row["id"],
            "timestamp": format_timestamp(row["timestamp"]),
            "thought": row["thought"],
            "commands_json": json_value_to_api_string(row["commands_json"]),
        }
        for row in rows
    ]


def get_current_metrics() -> dict[str, Any]:
    result: dict[str, Any] = {
        "temperature": None,
        "humidity": None,
        "water_temp": None,
        "ph": None,
        "ec": None,
    }

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT air_temp, humidity
                FROM telemetry_raw
                WHERE topic = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (CLIMATE_TOPIC,),
            )
            climate_row = cursor.fetchone()
            if climate_row:
                result["temperature"] = climate_row["air_temp"]
                result["humidity"] = climate_row["humidity"]

            cursor.execute(
                """
                SELECT water_temp
                FROM telemetry_raw
                WHERE topic = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (WATER_TOPIC,),
            )
            water_row = cursor.fetchone()
            if water_row:
                result["water_temp"] = water_row["water_temp"]

            cursor.execute(
                """
                SELECT ph
                FROM telemetry_raw
                WHERE ph IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
                """
            )
            ph_row = cursor.fetchone()
            if ph_row:
                result["ph"] = ph_row["ph"]

            cursor.execute(
                """
                SELECT ec
                FROM telemetry_raw
                WHERE ec IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
                """
            )
            ec_row = cursor.fetchone()
            if ec_row:
                result["ec"] = ec_row["ec"]

    return result


def get_hourly_history(metric_name: str, hours: int = 24) -> list[dict[str, Any]]:
    metric_config = {
        "temperature": "air_temp_avg",
        "humidity": "humidity_avg",
        "water_temp": "water_temp_avg",
        "ph": "ph_avg",
        "ec": "ec_avg",
    }
    if metric_name not in metric_config:
        raise ValueError(f"Unknown metric: {metric_name}")

    column_name = metric_config[metric_name]
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT hour_start, ROUND({column_name}::numeric, 2) AS avg_value
                FROM telemetry_hourly
                WHERE hour_start >= now() - (%s * interval '1 hour')
                  AND {column_name} IS NOT NULL
                ORDER BY hour_start ASC
                """,
                (hours,),
            )
            rows = cursor.fetchall()

    return [
        {
            "hour": format_timestamp(row["hour_start"])[:13] + ":00",
            "avg_value": float(row["avg_value"]) if row["avg_value"] is not None else None,
        }
        for row in rows
    ]


def aggregate_completed_hours() -> int:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_device(cursor, "unknown")
            cursor.execute(
                """
                WITH completed_hours AS (
                    SELECT
                        COALESCE(tray_id, 'unknown') AS tray_id,
                        COALESCE(sensor_type, 'unknown') AS sensor_type,
                        date_trunc('hour', recorded_at) AS hour_start,
                        AVG(air_temp) AS air_temp_avg,
                        MIN(air_temp) AS air_temp_min,
                        MAX(air_temp) AS air_temp_max,
                        COUNT(air_temp)::integer AS air_temp_count,
                        AVG(humidity) AS humidity_avg,
                        MIN(humidity) AS humidity_min,
                        MAX(humidity) AS humidity_max,
                        COUNT(humidity)::integer AS humidity_count,
                        AVG(water_temp) AS water_temp_avg,
                        MIN(water_temp) AS water_temp_min,
                        MAX(water_temp) AS water_temp_max,
                        COUNT(water_temp)::integer AS water_temp_count,
                        AVG(ph) AS ph_avg,
                        MIN(ph) AS ph_min,
                        MAX(ph) AS ph_max,
                        COUNT(ph)::integer AS ph_count,
                        AVG(ec) AS ec_avg,
                        MIN(ec) AS ec_min,
                        MAX(ec) AS ec_max,
                        COUNT(ec)::integer AS ec_count
                    FROM telemetry_raw
                    WHERE recorded_at < date_trunc('hour', now())
                    GROUP BY
                        COALESCE(tray_id, 'unknown'),
                        COALESCE(sensor_type, 'unknown'),
                        date_trunc('hour', recorded_at)
                ),
                missing_hours AS (
                    SELECT completed_hours.*
                    FROM completed_hours
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM telemetry_hourly
                        WHERE telemetry_hourly.tray_id = completed_hours.tray_id
                          AND telemetry_hourly.sensor_type = completed_hours.sensor_type
                          AND telemetry_hourly.hour_start = completed_hours.hour_start
                    )
                )
                INSERT INTO telemetry_hourly (
                    tray_id, sensor_type, hour_start,
                    air_temp, humidity, water_temp, ph, ec,
                    air_temp_avg, air_temp_min, air_temp_max, air_temp_count,
                    humidity_avg, humidity_min, humidity_max, humidity_count,
                    water_temp_avg, water_temp_min, water_temp_max, water_temp_count,
                    ph_avg, ph_min, ph_max, ph_count,
                    ec_avg, ec_min, ec_max, ec_count,
                    updated_at
                )
                SELECT
                    tray_id, sensor_type, hour_start,
                    air_temp_avg, humidity_avg, water_temp_avg, ph_avg, ec_avg,
                    air_temp_avg, air_temp_min, air_temp_max, air_temp_count,
                    humidity_avg, humidity_min, humidity_max, humidity_count,
                    water_temp_avg, water_temp_min, water_temp_max, water_temp_count,
                    ph_avg, ph_min, ph_max, ph_count,
                    ec_avg, ec_min, ec_max, ec_count,
                    now()
                FROM missing_hours
                ON CONFLICT (tray_id, sensor_type, hour_start) DO UPDATE SET
                    air_temp = EXCLUDED.air_temp,
                    humidity = EXCLUDED.humidity,
                    water_temp = EXCLUDED.water_temp,
                    ph = EXCLUDED.ph,
                    ec = EXCLUDED.ec,
                    air_temp_avg = EXCLUDED.air_temp_avg,
                    air_temp_min = EXCLUDED.air_temp_min,
                    air_temp_max = EXCLUDED.air_temp_max,
                    air_temp_count = EXCLUDED.air_temp_count,
                    humidity_avg = EXCLUDED.humidity_avg,
                    humidity_min = EXCLUDED.humidity_min,
                    humidity_max = EXCLUDED.humidity_max,
                    humidity_count = EXCLUDED.humidity_count,
                    water_temp_avg = EXCLUDED.water_temp_avg,
                    water_temp_min = EXCLUDED.water_temp_min,
                    water_temp_max = EXCLUDED.water_temp_max,
                    water_temp_count = EXCLUDED.water_temp_count,
                    ph_avg = EXCLUDED.ph_avg,
                    ph_min = EXCLUDED.ph_min,
                    ph_max = EXCLUDED.ph_max,
                    ph_count = EXCLUDED.ph_count,
                    ec_avg = EXCLUDED.ec_avg,
                    ec_min = EXCLUDED.ec_min,
                    ec_max = EXCLUDED.ec_max,
                    ec_count = EXCLUDED.ec_count,
                    updated_at = now()
                RETURNING id
                """
            )
            return len(cursor.fetchall())


def delete_old_raw_data(retention_hours: int = 24) -> int:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM telemetry_raw
                WHERE recorded_at < now() - (%s * interval '1 hour')
                  AND EXISTS (
                      SELECT 1
                      FROM telemetry_hourly
                      WHERE telemetry_hourly.tray_id = COALESCE(telemetry_raw.tray_id, 'unknown')
                        AND telemetry_hourly.sensor_type = COALESCE(telemetry_raw.sensor_type, 'unknown')
                        AND telemetry_hourly.hour_start = date_trunc('hour', telemetry_raw.recorded_at)
                  )
                RETURNING id
                """,
                (retention_hours,),
            )
            return len(cursor.fetchall())


def save_anomaly_event(
    *,
    tray_id: str | None,
    metric_name: str,
    severity: str,
    value: float | None,
    message: str,
    event_type: str,
    sensor_type: str | None = None,
    payload: dict[str, Any] | None = None,
    cooldown_minutes: int = 5,
) -> bool:
    normalized_tray_id = normalize_device_id(tray_id) or "unknown"
    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_device(cursor, normalized_tray_id)
            cursor.execute(
                """
                WITH recent_duplicate AS (
                    SELECT 1
                    FROM anomaly_events
                    WHERE tray_id = %s
                      AND event_type = %s
                      AND metric_name = %s
                      AND created_at >= now() - (%s * interval '1 minute')
                    LIMIT 1
                )
                INSERT INTO anomaly_events (
                    tray_id, sensor_type, event_type, metric_name,
                    severity, value, message, payload, created_at
                )
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, now()
                WHERE NOT EXISTS (SELECT 1 FROM recent_duplicate)
                RETURNING id
                """,
                (
                    normalized_tray_id,
                    event_type,
                    metric_name,
                    cooldown_minutes,
                    normalized_tray_id,
                    sensor_type,
                    event_type,
                    metric_name,
                    severity,
                    value,
                    message,
                    Jsonb(payload or {}),
                ),
            )
            return cursor.fetchone() is not None


def get_recent_anomaly_events(hours: int = 24) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, tray_id, sensor_type, event_type, metric_name,
                    severity, value, message, payload, created_at
                FROM anomaly_events
                WHERE created_at >= now() - (%s * interval '1 hour')
                ORDER BY created_at DESC, id DESC
                """,
                (hours,),
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row["id"],
            "tray_id": row["tray_id"],
            "sensor_type": row["sensor_type"],
            "event_type": row["event_type"],
            "metric_name": row["metric_name"],
            "severity": row["severity"],
            "value": row["value"],
            "message": row["message"],
            "payload": row["payload"],
            "created_at": format_timestamp(row["created_at"]),
        }
        for row in rows
    ]


def get_recent_hourly_summary(hours: int = 24) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    tray_id, sensor_type, hour_start,
                    air_temp_avg, air_temp_min, air_temp_max, air_temp_count,
                    humidity_avg, humidity_min, humidity_max, humidity_count,
                    water_temp_avg, water_temp_min, water_temp_max, water_temp_count,
                    ph_avg, ph_min, ph_max, ph_count,
                    ec_avg, ec_min, ec_max, ec_count
                FROM telemetry_hourly
                WHERE hour_start >= now() - (%s * interval '1 hour')
                ORDER BY hour_start ASC
                """,
                (hours,),
            )
            rows = cursor.fetchall()

    return [
        {
            **row,
            "hour_start": format_timestamp(row["hour_start"]),
        }
        for row in rows
    ]


def clear_telemetry_raw() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM telemetry_raw")
