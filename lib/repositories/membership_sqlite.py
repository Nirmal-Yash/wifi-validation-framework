"""SQLite persistence for project membership and workspace identity."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from lib.domain.resources import ProjectMembership
from .interfaces import RepositoryConflictError
from .sqlite import SQLiteDatabase


def _membership(row: sqlite3.Row | None) -> ProjectMembership | None:
    if row is None:
        return None
    return ProjectMembership(
        username=row["username"],
        project_id=row["project_id"],
        role=row["role"],
        created_at=datetime.fromisoformat(row["created_at"]),
        created_by=row["created_by"],
    )


class SQLiteProjectMembershipRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, membership: ProjectMembership) -> None:
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO project_memberships(
                        username, project_id, role, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        membership.username,
                        membership.project_id,
                        membership.role,
                        membership.created_at.isoformat(),
                        membership.created_by,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "foreign key" in message:
                raise RepositoryConflictError("membership references a project that does not exist") from exc
            raise RepositoryConflictError(
                f"membership already exists for {membership.username}:{membership.project_id}"
            ) from exc

    def get(self, username: str, project_id: str) -> ProjectMembership | None:
        with self.database.connection() as connection:
            return _membership(connection.execute(
                """SELECT * FROM project_memberships
                   WHERE username=? AND project_id=?""",
                (username, project_id),
            ).fetchone())

    def list_for_user(self, username: str) -> list[ProjectMembership]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM project_memberships
                   WHERE username=? ORDER BY created_at, project_id""",
                (username,),
            ).fetchall()
        return [_membership(row) for row in rows]

    def list_for_project(self, project_id: str) -> list[ProjectMembership]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM project_memberships
                   WHERE project_id=? ORDER BY username COLLATE NOCASE""",
                (project_id,),
            ).fetchall()
        return [_membership(row) for row in rows]

    def delete(self, username: str, project_id: str) -> bool:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "DELETE FROM project_memberships WHERE username=? AND project_id=?",
                (username, project_id),
            )
            return cursor.rowcount == 1
