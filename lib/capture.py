import subprocess, time, pyshark

def start_capture(interface, output_file, duration=10):
    proc = subprocess.Popen(
        ["tcpdump", "-i", interface, "-w", output_file,
         "-G", str(duration), "-W", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(duration + 1)
    proc.terminate()
    return output_file

def read_pcap(filepath):
    cap = pyshark.FileCapture(filepath)
    packets = [pkt for pkt in cap]
    cap.close()
    return packets

def filter_pcap(filepath, display_filter):
    cap = pyshark.FileCapture(filepath,
           display_filter=display_filter)
    packets = [pkt for pkt in cap]
    cap.close()
    return packets
