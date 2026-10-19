"""Executable relational review; metadata is the only model definition."""
import argparse
import json
import os


def check(metadata):
    errors, names = [], set()
    for table in metadata.sorted_tables:
        if not table.primary_key.columns:
            errors.append(table.name + ": missing primary key")
        for constraint in table.constraints:
            if constraint.name:
                # Constraint names are table scoped in PostgreSQL. Indexes are not.
                key = (table.name, constraint.name)
                if key in names:
                    errors.append(table.name + ": duplicate constraint " + constraint.name)
                names.add(key)
        for fk in table.foreign_key_constraints:
            targets = [e.column for e in fk.elements]
            target_table = targets[0].table
            if "project_id" in table.c and "project_id" in target_table.c:
                if "project_id" not in fk.column_keys or "project_id" not in [c.name for c in targets]:
                    errors.append(table.name + ": foreign key omits project isolation: " + str(fk.name))
        if table.name == "binding_slots" and table.c.slot_key.nullable:
            errors.append("binding_slots.slot_key must be non-null")
    required = {"binding_slots", "binding_candidates", "media_reviews", "binding_decisions", "current_bindings",
                "job_input_media", "job_input_versions", "operation_inputs", "operation_outputs", "artifact_versions"}
    for name in sorted(required - set(metadata.tables)):
        errors.append("missing relation: " + name)
    return errors


def describe(metadata):
    rows = ["# PostgreSQL 资源表字典", "", "由 `scripts/project/schema.py describe` 生成；表定义与迁移是规范。", "",
            "| 表 | 一行的键／粒度 | 关系外键 |", "| --- | --- | --- |"]
    edges = set()
    for table in metadata.sorted_tables:
        keys = ", ".join(c.name for c in table.primary_key.columns)
        links = []
        for fk in table.foreign_key_constraints:
            target = next(iter(fk.elements)).column.table.name
            links.append(",".join(fk.column_keys) + " → " + target)
            edges.add((target, table.name))
        rows.append("| " + table.name + " | " + keys + " | " + "; ".join(sorted(links)) + " |")
    rows += ["", "```mermaid", "erDiagram"]
    rows += ["    " + parent + " ||--o{ " + child + ' : "references"' for parent, child in sorted(edges)]
    rows += ["```", ""]
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="VSC PostgreSQL 关系模型检查")
    parser.add_argument("command", choices=["check", "describe", "migrate"])
    parser.add_argument("--database-env", help="显式连接变量名；不输出凭据")
    parser.add_argument("--schema", help="实际检查或迁移的 PostgreSQL schema")
    args = parser.parse_args(argv)
    try:
        from vsc.adapters.persistence.postgres.schema import metadata
        from sqlalchemy import create_engine, text
    except ImportError:
        parser.error("需要安装 vsc-workflow[postgres] 可选依赖")
    if args.command == "describe":
        print(describe(metadata))
        return
    errors = check(metadata)
    if args.command == "migrate" and not args.database_env:
        parser.error("迁移必须显式提供 --database-env")
    if args.database_env:
        url = os.environ.get(args.database_env)
        if not url:
            parser.error("未加载 " + args.database_env + "；请在工作区根目录 .env 中配置后重新启动工具")
        if args.schema and not args.schema.replace("_", "").isalnum():
            parser.error("schema 名称只能含字母、数字和下划线")
        options = {"options": "-csearch_path=" + args.schema} if args.schema else {}
        engine = None
        try:
            from sqlalchemy.exc import SQLAlchemyError
            engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1), connect_args=options)
            with engine.begin() as conn:
                if args.command == "migrate":
                    from alembic import command
                    from alembic.config import Config
                    from vsc.bootstrap import repository_root
                    config = Config(str(repository_root() / "migrations/postgres/alembic.ini"))
                    config.attributes["connection"] = conn
                    command.upgrade(config, "head")
                else:
                    from alembic.autogenerate import compare_metadata
                    from alembic.migration import MigrationContext
                    differences = compare_metadata(MigrationContext.configure(conn), metadata)
                    if differences:
                        errors.append("实际数据库与规范表定义不一致: " + repr(differences))
        except (SQLAlchemyError, ValueError) as error:
            errors.append("数据库验证／迁移失败，请核对 " + args.database_env + " 的连接与权限（" + type(error).__name__ + "）")
        finally:
            if engine is not None:
                engine.dispose()
    print(json.dumps({"passed": not errors, "tables": len(metadata.tables), "errors": errors}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
