"""Offline guest-side evidence for explicitly requested mixed peer reports."""

PING_REPORT_PATH = "/var/www/polmon/pings.txt"
PING_SCRIPT = """\
import json, os, subprocess, sys, time
peers, out = json.loads(sys.argv[1]), sys.argv[2]
deadline = time.monotonic() + 150
while True:
    lines = []
    for peer, address in peers:
        result = subprocess.run(['ping', '-c', '1', '-W', '1', address],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=4)
        lines.append(peer + (' ok' if result.returncode == 0 else ' fail'))
    with open(out + '.tmp', 'w') as stream:
        stream.write('\\n'.join(lines) + '\\n')
    os.replace(out + '.tmp', out)
    if all(line.endswith(' ok') for line in lines) or time.monotonic() > deadline:
        break
    time.sleep(2)
"""
