#!/usr/bin/python3

import sys
import asyncio
import os
import click

from .master import ClashMaster
from .slave import ClashSlave

global logfile
logfile = None


def log(msg):
    global logfile
    if logfile:
        logfile.write(f"{msg}\n")
        logfile.flush()


def nolog(_):
    pass


@click.command()
@click.option('--debug', '-d', is_flag=True, help='debug')
@click.argument('session', required=False)
def main(debug, session):
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

    logger = nolog
    if debug:
        logger = log
        if session:
            logfile = open("log-slave.txt", "w+")
        else:
            logfile = open("log-master.txt", "w+")

    if session:
        slave = ClashSlave(log=logger, url=url)
        loop.run_until_complete(slave.run(session))
    else:
        master = ClashMaster(log=logger, url=url)
        loop.run_until_complete(master.run())


if __name__ == "__main__":
    main()
