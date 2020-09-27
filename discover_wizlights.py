import socket

def discover(verbose=True, port=38899, timeout=0.2):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    message = r'{"method":"getSystemConfig","params":{}}'.encode()
    sock.sendto(message, ('<broadcast>', port))

    sock.settimeout(timeout)

    responses = {}
    response = True
    while response:
        try:
            response, (ipaddr, port) = sock.recvfrom(2**16)
            responses[ipaddr] = response
        except (BlockingIOError, socket.timeout) as e:
            response = None

    return responses

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', default=38899, type=int)
    parser.add_argument('-t', '--timeout', default=0.2, type=float)

    args = parser.parse_args()

    responses = discover(port=args.port, timeout=args.timeout)
    first = True
    for ip, resp in responses.items():
        if not first:
            print('')
        print('IP address', ip, ':\n', resp)
        first = False
