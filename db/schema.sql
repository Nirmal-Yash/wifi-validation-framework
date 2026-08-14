PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS firmware_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firmware_version TEXT NOT NULL UNIQUE,
    release_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','ARCHIVED'))
);

CREATE TABLE IF NOT EXISTS test_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firmware_version TEXT NOT NULL,
    test_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PASSED','FAILED','SKIPPED','ERROR','XFAIL','XPASS')),
    execution_time REAL,
    error_message TEXT,
    pcap_path TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(firmware_version) REFERENCES firmware_metadata(firmware_version)
);

CREATE TABLE IF NOT EXISTS topologies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'local' CHECK(source IN ('local','gns3','import')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topology_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topology_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','VALIDATED','ACTIVE','ARCHIVED')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(topology_id, version),
    FOREIGN KEY(topology_id) REFERENCES topologies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS topology_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topology_version_id INTEGER NOT NULL,
    node_key TEXT NOT NULL,
    name TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'generic',
    namespace TEXT,
    interface_name TEXT,
    config_path TEXT,
    x REAL NOT NULL DEFAULT 0,
    y REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(topology_version_id, node_key),
    FOREIGN KEY(topology_version_id) REFERENCES topology_versions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS topology_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topology_version_id INTEGER NOT NULL,
    source_node_id INTEGER NOT NULL,
    target_node_id INTEGER NOT NULL,
    source_interface TEXT,
    target_interface TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(topology_version_id) REFERENCES topology_versions(id) ON DELETE CASCADE,
    FOREIGN KEY(source_node_id) REFERENCES topology_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target_node_id) REFERENCES topology_nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firmware_version TEXT NOT NULL,
    topology_version_id INTEGER,
    mode TEXT NOT NULL DEFAULT 'tier1' CHECK(mode IN ('tier1','tier2')),
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','RUNNING','PASSED','FAILED','ERROR','CANCELLED')),
    started_at DATETIME,
    finished_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(firmware_version) REFERENCES firmware_metadata(firmware_version),
    FOREIGN KEY(topology_version_id) REFERENCES topology_versions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER NOT NULL,
    test_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PASSED','FAILED','SKIPPED','ERROR','XFAIL','XPASS')),
    duration REAL,
    error_message TEXT,
    evidence_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER,
    test_result_id INTEGER,
    kind TEXT NOT NULL CHECK(kind IN ('pcap','log','json','text','screenshot','artifact')),
    path TEXT NOT NULL,
    sha256 TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE,
    FOREIGN KEY(test_result_id) REFERENCES test_results(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    firmware_version TEXT NOT NULL,
    topology_version_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, firmware_version),
    FOREIGN KEY(firmware_version) REFERENCES firmware_metadata(firmware_version),
    FOREIGN KEY(topology_version_id) REFERENCES topology_versions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS regressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_id INTEGER NOT NULL,
    execution_id INTEGER NOT NULL,
    test_name TEXT NOT NULL,
    baseline_status TEXT NOT NULL,
    candidate_status TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'HIGH' CHECK(severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(baseline_id) REFERENCES baselines(id) ON DELETE CASCADE,
    FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_test_logs_fw ON test_logs(firmware_version);
CREATE INDEX IF NOT EXISTS idx_test_logs_timestamp ON test_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_topology_nodes_version ON topology_nodes(topology_version_id);
CREATE INDEX IF NOT EXISTS idx_topology_links_version ON topology_links(topology_version_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
CREATE INDEX IF NOT EXISTS idx_results_execution ON test_results(execution_id);
CREATE INDEX IF NOT EXISTS idx_evidence_execution ON evidence(execution_id);
