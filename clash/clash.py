#!/usr/bin/python3

import sys
import asyncio

from master import ClashMaster
from slave import ClashSlave

global logfile
logfile = None


def log(msg):
    global logfile
    if logfile:
        logfile.write(f"{msg}\n")
        logfile.flush()


if __name__ == "__main__":

    loop = asyncio.get_event_loop()

    if len(sys.argv) > 1:
        logfile = open("log-slave.txt", "w+")
        slave = ClashSlave(log=log)
        loop.run_until_complete(slave.run(sys.argv[1]))
    else:
        logfile = open("log-master.txt", "w+")
        master = ClashMaster(log=log)
        loop.run_until_complete(master.run())
