from flask import Flask, render_template
import sqlite3
import os

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), '../db/results.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    
    total_tests = conn.execute("SELECT COUNT(*) as c FROM test_logs").fetchone()['c']
    passed_tests = conn.execute("SELECT COUNT(*) as c FROM test_logs WHERE status='PASSED'").fetchone()['c']
    failed_tests = total_tests - passed_tests
    pass_rate = round((passed_tests / total_tests * 100), 1) if total_tests > 0 else 0
    
    recent_failures = conn.execute("""
        SELECT firmware_version, test_name, error_message, timestamp 
        FROM test_logs WHERE status = 'FAILED' ORDER BY timestamp DESC LIMIT 5
    """).fetchall()

    trend_data_raw = conn.execute("""
        SELECT firmware_version, 
               SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pass_rate
        FROM test_logs GROUP BY firmware_version ORDER BY firmware_version ASC LIMIT 10
    """).fetchall()
    
    trend_data = [dict(row) for row in trend_data_raw]
    conn.close()
    
    return render_template('dashboard.html', 
                           total=total_tests, 
                           passed=passed_tests, 
                           failed=failed_tests, 
                           rate=pass_rate,
                           failures=recent_failures,
                           trends=trend_data)

@app.route('/topology')
def topology():
    return render_template('topology.html')

@app.route('/history')
def history():
    conn = get_db_connection()
    logs = conn.execute("SELECT * FROM test_logs ORDER BY timestamp DESC").fetchall()
    conn.close()
    return render_template('history.html', logs=logs)

@app.route('/about')
def about():
    return render_template('about.html')

if __name__ == '__main__':
    print("[*] NetRegress QA Dashboard starting at http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
