#!/usr/bin/python3

import sys
import asyncio
import os

from .master import ClashMaster
from .slave import ClashSlave

global logfile
logfile = None


def log(msg):
    global logfile
    if logfile:
        logfile.write(f"{msg}\n")
        logfile.flush()


def main():
    global logfile
    loop = asyncio.get_event_loop()
    url = "http://localhost:8080/clash"
    try:
        configfile = open(f"{os.path.expanduser('~')}/.clashrc", "r")
        for line in configfile.readlines():
            if line.startswith("SERVER"):
                vals = line.split("=")
                if len(vals) < 2:
                    print("Please specify SERVER = http://... in ~/.clashrc")
                    sys.exit(1)
                url = vals[1].strip()
    except Exception:
        pass

    if len(sys.argv) > 1:
        logfile = open("log-slave.txt", "w+")
        slave = ClashSlave(log=log, url=url)
        loop.run_until_complete(slave.run(sys.argv[1]))
    else:
        logfile = open("log-master.txt", "w+")
        master = ClashMaster(log=log, url=url)
        loop.run_until_complete(master.run())


if __name__ == "__main__":
    main()
