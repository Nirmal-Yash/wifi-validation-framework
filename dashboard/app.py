from flask import Flask, render_template
import sqlite3
import os

print("\n[*] Initializing StyleFusion Dashboard...")
app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), '../db/results.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    summary_data = conn.execute("""
        SELECT firmware_version, COUNT(*) as total_tests,
        SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) as passed_tests,
        SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed_tests
        FROM test_logs GROUP BY firmware_version ORDER BY firmware_version DESC
    """).fetchall()

    recent_failures = conn.execute("""
        SELECT firmware_version, test_name, error_message, pcap_path, timestamp 
        FROM test_logs WHERE status = 'FAILED' ORDER BY timestamp DESC
    """).fetchall()
    conn.close()
    return render_template('index.html', summaries=summary_data, failures=recent_failures)

if __name__ == '__main__':
    print("[*] Dashboard starting! Open your browser and go to http://127.0.0.1:5000\n")
    app.run(host='0.0.0.0', port=5000, debug=True)
