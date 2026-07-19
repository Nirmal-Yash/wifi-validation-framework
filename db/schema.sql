CREATE TABLE IF NOT EXISTS firmware_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firmware_version TEXT NOT NULL UNIQUE,
    release_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS test_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firmware_version TEXT NOT NULL,
    test_name TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_time REAL,
    error_message TEXT,
    pcap_path TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(firmware_version) REFERENCES firmware_metadata(firmware_version)
);
