import sqlite3
import os
import sys

class RegressionDiffEngine:
    def __init__(self, db_path="db/results.db"):
        self.db_path = db_path

    def run_regression_analysis(self, target_version, baseline_version="1.0.0"):
        """Compares test results from a target firmware against a baseline to flag regressions."""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database tracking store not found at target: {self.db_path}")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT test_name, status, execution_time FROM test_logs WHERE firmware_version = ?", 
            (baseline_version,)
        )
        baseline_records = {row[0]: {"status": row[1], "time": row[2]} for row in cursor.fetchall()}

        cursor.execute(
            "SELECT test_name, status, execution_time, error_message, pcap_path FROM test_logs WHERE firmware_version = ?", 
            (target_version,)
        )
        target_records = cursor.fetchall()
        conn.close()

        regressions = []
        improvements = []

        for row in target_records:
            t_name, t_status, t_time, t_err, t_pcap = row
            if t_name in baseline_records:
                base = baseline_records[t_name]
                
                if base["status"] == "PASSED" and t_status == "FAILED":
                    regressions.append({
                        "test_name": t_name,
                        "baseline_status": base["status"],
                        "current_status": t_status,
                        "error_message": t_err,
                        "pcap_path": t_pcap
                    })
                elif base["status"] == "FAILED" and t_status == "PASSED":
                    improvements.append({
                        "test_name": t_name,
                        "baseline_status": base["status"],
                        "current_status": t_status
                    })

        return {
            "target_version": target_version,
            "baseline_version": baseline_version,
            "regressions_detected": regressions,
            "improvements_detected": improvements
        }

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "1.0.1"
    engine = RegressionDiffEngine()
    analysis = engine.run_regression_analysis(target_version=target)
    
    print(f"\n=== REGRESSION ANALYSIS FOR FIRMWARE v{analysis['target_version']} ===")
    print(f"Compared against Baseline: v{analysis['baseline_version']}")
    print(f"Regressions Identified: {len(analysis['regressions_detected'])}")
    
    for entry in analysis["regressions_detected"]:
        print(f"  [-] ALERT: Regression found in test case '{entry['test_name']}'")
        print(f"      Details: {entry['error_message']}")
