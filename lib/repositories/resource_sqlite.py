"""SQLite repositories for the initial Organization -> Project -> Lab model."""
from __future__ import annotations

from datetime import datetime
import sqlite3

from lib.domain.resources import Lab, Organization, Project, ResourceStatus
from .interfaces import RepositoryConflictError
from .sqlite import SQLiteDatabase


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _organization(row: sqlite3.Row | None) -> Organization | None:
    if row is None:
        return None
    return Organization(
        organization_id=row["organization_id"],
        slug=row["slug"],
        name=row["name"],
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        status=ResourceStatus(row["status"]),
    )


def _project(row: sqlite3.Row | None) -> Project | None:
    if row is None:
        return None
    return Project(
        project_id=row["project_id"],
        organization_id=row["organization_id"],
        slug=row["slug"],
        name=row["name"],
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        status=ResourceStatus(row["status"]),
    )


def _lab(row: sqlite3.Row | None) -> Lab | None:
    if row is None:
        return None
    return Lab(
        lab_id=row["lab_id"],
        project_id=row["project_id"],
        name=row["name"],
        provider_id=row["provider_id"],
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        topology_version=int(row["topology_version"]),
        status=ResourceStatus(row["status"]),
    )


def _raise_conflict(entity: str, exc: sqlite3.IntegrityError) -> None:
    message = str(exc).lower()
    if "foreign key" in message:
        raise RepositoryConflictError(f"{entity} references a parent resource that does not exist") from exc
    raise RepositoryConflictError(f"{entity} conflicts with an existing resource") from exc


class SQLiteOrganizationRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, organization: Organization) -> None:
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO organizations(
                        organization_id, slug, name, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        organization.organization_id, organization.slug, organization.name,
                        organization.status.value, organization.created_at.isoformat(),
                        organization.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            _raise_conflict("organization", exc)

    def update(self, organization: Organization) -> None:
        try:
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """UPDATE organizations SET slug=?, name=?, status=?, updated_at=?
                       WHERE organization_id=?""",
                    (
                        organization.slug, organization.name, organization.status.value,
                        organization.updated_at.isoformat(), organization.organization_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RepositoryConflictError(
                        f"organization does not exist: {organization.organization_id}"
                    )
        except sqlite3.IntegrityError as exc:
            _raise_conflict("organization", exc)

    def get(self, organization_id: str) -> Organization | None:
        with self.database.connection() as connection:
            return _organization(connection.execute(
                "SELECT * FROM organizations WHERE organization_id=?", (organization_id,)
            ).fetchone())

    def get_by_slug(self, slug: str) -> Organization | None:
        with self.database.connection() as connection:
            return _organization(connection.execute(
                "SELECT * FROM organizations WHERE slug=?", (slug,)
            ).fetchone())

    def list(self) -> list[Organization]:
        with self.database.connection() as connection:
            return [
                _organization(row) for row in connection.execute(
                    "SELECT * FROM organizations ORDER BY name COLLATE NOCASE, organization_id"
                ).fetchall()
            ]


class SQLiteProjectRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, project: Project) -> None:
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO projects(
                        project_id, organization_id, slug, name, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project.project_id, project.organization_id, project.slug, project.name,
                        project.status.value, project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            _raise_conflict("project", exc)

    def update(self, project: Project) -> None:
        try:
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """UPDATE projects SET organization_id=?, slug=?, name=?, status=?, updated_at=?
                       WHERE project_id=?""",
                    (
                        project.organization_id, project.slug, project.name,
                        project.status.value, project.updated_at.isoformat(), project.project_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RepositoryConflictError(f"project does not exist: {project.project_id}")
        except sqlite3.IntegrityError as exc:
            _raise_conflict("project", exc)

    def get(self, project_id: str) -> Project | None:
        with self.database.connection() as connection:
            return _project(connection.execute(
                "SELECT * FROM projects WHERE project_id=?", (project_id,)
            ).fetchone())

    def list_for_organization(self, organization_id: str) -> list[Project]:
        with self.database.connection() as connection:
            return [
                _project(row) for row in connection.execute(
                    """SELECT * FROM projects WHERE organization_id=?
                       ORDER BY name COLLATE NOCASE, project_id""",
                    (organization_id,),
                ).fetchall()
            ]


class SQLiteLabRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, lab: Lab) -> None:
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO labs(
                        lab_id, project_id, name, provider_id, topology_version,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        lab.lab_id, lab.project_id, lab.name, lab.provider_id,
                        lab.topology_version, lab.status.value, lab.created_at.isoformat(),
                        lab.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            _raise_conflict("lab", exc)

    def update(self, lab: Lab) -> None:
        try:
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """UPDATE labs SET project_id=?, name=?, provider_id=?, topology_version=?,
                       status=?, updated_at=? WHERE lab_id=?""",
                    (
                        lab.project_id, lab.name, lab.provider_id, lab.topology_version,
                        lab.status.value, lab.updated_at.isoformat(), lab.lab_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RepositoryConflictError(f"lab does not exist: {lab.lab_id}")
        except sqlite3.IntegrityError as exc:
            _raise_conflict("lab", exc)

    def get(self, lab_id: str) -> Lab | None:
        with self.database.connection() as connection:
            return _lab(connection.execute(
                "SELECT * FROM labs WHERE lab_id=?", (lab_id,)
            ).fetchone())

    def list_for_project(self, project_id: str) -> list[Lab]:
        with self.database.connection() as connection:
            return [
                _lab(row) for row in connection.execute(
                    """SELECT * FROM labs WHERE project_id=?
                       ORDER BY name COLLATE NOCASE, lab_id""",
                    (project_id,),
                ).fetchall()
            ]
