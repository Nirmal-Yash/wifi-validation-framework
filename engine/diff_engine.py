import sqlite3
import os

def compare_firmware(db_path, fw_a, fw_b):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query = """
        SELECT a.test_name, a.status as status_a, b.status as status_b
        FROM test_logs a JOIN test_logs b ON a.test_name = b.test_name
        WHERE a.firmware_version = ? AND b.firmware_version = ?
    """
    results = conn.execute(query, (fw_a, fw_b)).fetchall()
    conn.close()
    return [dict(r) for r in results]
