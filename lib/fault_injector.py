import subprocess

def link_down(interface):
    subprocess.run(["sudo","ip","link","set",
                    interface,"down"], check=True)

def link_up(interface):
    subprocess.run(["sudo","ip","link","set",
                    interface,"up"], check=True)

def add_delay(interface, delay_ms=100):
    subprocess.run(["sudo","tc","qdisc","add","dev",
        interface,"root","netem","delay",
        f"{delay_ms}ms"], check=True)

def add_packet_loss(interface, loss_pct=10):
    subprocess.run(["sudo","tc","qdisc","add","dev",
        interface,"root","netem","loss",
        f"{loss_pct}%"], check=True)

def clear_conditions(interface):
    subprocess.run(["sudo","tc","qdisc","del","dev",
        interface,"root"], check=False)
