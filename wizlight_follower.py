#!/usr/bin/env python3
"""
example script usage:
python3 wizlight_follower.py 192.168.1.2,wemo:192.168.1.13 192.168.1.32,192.168.1.33 -s 0.1 -c 3
"""

import sys
import json
import socket
import asyncio
from time import sleep
from argparse import ArgumentParser
import logging
log = logging.getLogger('wizlight_follower')

from pywizlight import wizlight as Wizlight
try:
    # pywemo only needed if there are wemo insight followers
    import pywemo
except ImportError:
    pywemo = None

WIZ__CONTROL_PORT = 38899

class WeMoInsightAdapter:
    def __init__(self, wemoinsight):
        if not isinstance(wemoinsight, pywemo.Insight):
            raise TypeError(f'Input to WeMoInsightAdapter is a '
                            f'{type(wemoinsight)} not a pywemo.Insight!')

        self.insight = wemoinsight

    async def turn_on(self):
        return self.insight.on()

    async def turn_off(self):
        return self.insight.off()

    async def lightSwitch(self):
        return self.insight.toggle()


async def main(follow_ips, switch_ips, homeid=None, sleep_secs=1, cycle_threshold=1):
    follow_lights = []
    for ip in follow_ips:
        if ip.startswith('wemo:'):
            if pywemo is None:
                log.error('Wemo light requested but pywemo is not installed')
                return -1
            address = ip[5:] # strip the 'wemo:' part
            port = pywemo.ouimeaux_device.probe_wemo(address)
            url = f'http://{address}:{port}/setup.xml'
            device = pywemo.discovery.device_from_description(url, None)
            light = WeMoInsightAdapter(device)
        else:
            #assume wizlight
            light = Wizlight(ip)
            config = await light.getBulbConfig()
            if 'result' in config:
                if homeid is not None and config['result']['homeId'] != homeid:
                    log.error(f"lighbulb at {light.ip} is in homeid "
                            f"{config['result']['homeId']} instead of {homeid}")
                    return 1
            else:
                log.error(f'lighbulb at {light.ip} is not responding')
                return 2

        follow_lights.append(light)

    switch_sockets = []
    switch_cycles = []
    for ip in switch_ips:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ip, WIZ__CONTROL_PORT))
        s.settimeout(0)
        switch_sockets.append(s)
        switch_cycles.append(0)

    config_message = r'{"method":"getSystemConfig","params":{}}'.encode('utf-8')
    for s in switch_sockets:
        s.send(config_message)
    sleep(sleep_secs)

    while True:
        try:
            turn_lights_on = None
            for i, s in enumerate(switch_sockets):
                try:
                    response = s.recv(1024)  # raises BlockingIOError if no response

                    log.info(f'Light at {s.getpeername()[0]} is on')
                    config = json.loads(response)

                    if homeid is None or config['result']['homeId'] == homeid:

                        switch_cycles[i] += 1
                    elif homeid is not None:
                        log.error(f'Light at {s.getpeername()[0]} is on but not the right homeid')
                        return 3

                except BlockingIOError:
                    log.info(f'no response from light at {s.getpeername()[0]}')
                    switch_cycles[i] -= 1

                except ConnectionRefusedError:
                    log.warning(f'connection refused to light at {s.getpeername()[0]} ignorable unless repeated')
                    continue
                s.send(config_message)

            # check if something has crossed a threshold
            if sum(switch_cycles) <= 0:
                # might need a switch off - check if they're all 0 or less and at least one is 0
                if all([c<=0 for c in switch_cycles]) and any([c==0 for c in switch_cycles]):
                    log.info(f'switch lights status is {switch_cycles}, so followers off')
                    # turn followers off
                    await asyncio.gather(*[light.turn_off() for light in follow_lights])
            elif sum(switch_cycles) >= cycle_threshold*len(switch_cycles):
                # might need a switch on
                if all([c>=cycle_threshold for c in switch_cycles]) and any([c==cycle_threshold for c in switch_cycles]):
                    log.info(f'switch lights status is {switch_cycles}, so followers on')
                    # turn followers on
                    await asyncio.gather(*[light.turn_on() for light in follow_lights])

            # reset any out-of-range cycle counts
            for i in range(len(switch_cycles)):
                if switch_cycles[i] < 0:
                    switch_cycles[i] = 0
                if switch_cycles[i] > cycle_threshold:
                    switch_cycles[i] = cycle_threshold

            sleep(sleep_secs)
        except KeyboardInterrupt:
            return 0


if __name__ == '__main__':
    logging.basicConfig()

    parser = ArgumentParser()
    parser.add_argument('follow_ips')
    parser.add_argument('switch_ips')
    parser.add_argument('-s', '--sleepsecs', default=1, type=float)
    parser.add_argument('-i', '--homeid', default=1501360, type=int)
    parser.add_argument('-c', '--cyclethreshold', default=1, type=int)
    parser.add_argument('-q', '--quiet')

    args = parser.parse_args()

    if args.quiet:
        log.setLevel(logging.WARNING)
    else:
        log.setLevel(logging.INFO)

    retcode = asyncio.run(main(args.follow_ips.split(','), args.switch_ips.split(','),
                           args.homeid, args.sleepsecs, args.cyclethreshold))
    sys.exit(retcode)
