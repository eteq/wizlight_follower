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


async def main(follow_ips, switch_ips, homeid=None, sleepsecs=1):
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
    switch_powered = []
    for ip in switch_ips:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ip, WIZ__CONTROL_PORT))
        s.settimeout(0)
        switch_sockets.append(s)
        switch_powered.append(None)

    config_message = r'{"method":"getSystemConfig","params":{}}'.encode('utf-8')
    for s in switch_sockets:
        s.send(config_message)
    sleep(sleepsecs)

    while True:
        try:
            toggle = None
            for i, s in enumerate(switch_sockets):
                try:
                    response = s.recv(1024)  # raises BlockingIOError if no response

                    log.info(f'Light at {s.getpeername()[0]} is on')
                    config = json.loads(response)

                    if homeid is None or config['result']['homeId'] == homeid:
                        if not switch_powered[i] and switch_powered[i]  is not None:
                            log.info(f'light at {s.getpeername()[0]} now on, so followers on')
                            toggle = True
                        switch_powered[i] = True
                    elif homeid is not None:
                        log.error(f'Light at {s.getpeername()[0]} is on but not the right homeid')
                        return 3

                except BlockingIOError:
                    log.info(f'no response from light at {s.getpeername()[0]}')
                    if switch_powered[i]:
                        log.info(f'light at {s.getpeername()[0]} now off, so followers off')
                        toggle = False
                    switch_powered[i] = False

                except ConnectionRefusedError:
                    log.warning(f'connection refused to light at {s.getpeername()[0]} ignorable unless repeated')
                    continue

                s.send(config_message)
            if toggle is not None:
                if toggle:
                    # turn followers on
                    await asyncio.gather(*[light.turn_on() for light in follow_lights])
                else:
                    # turn followers off
                    await asyncio.gather(*[light.turn_off() for light in follow_lights])

            sleep(sleepsecs)
        except KeyboardInterrupt:
            return 0


if __name__ == '__main__':
    logging.basicConfig()

    parser = ArgumentParser()
    parser.add_argument('follow_ips')
    parser.add_argument('switch_ips')
    parser.add_argument('-s', '--sleepsecs', default=1, type=float)
    parser.add_argument('-i', '--homeid', default=1501360, type=int)
    parser.add_argument('-q', '--quiet')

    args = parser.parse_args()

    if args.quiet:
        log.setLevel(logging.WARNING)
    else:
        log.setLevel(logging.INFO)

    retcode = asyncio.run(main(args.follow_ips.split(','), args.switch_ips.split(','),
                           args.homeid, args.sleepsecs))
    sys.exit(retcode)
