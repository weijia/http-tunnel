#!/usr/bin/env python
import socket
import httplib, urllib
import traceback
from uuid import uuid4
import threading
import argparse
import sys
import logging

BUFFER = 1024 * 50

#set global timeout
#socket.setdefaulttimeout(10)


class Connection():
    
    def __init__(self, connection_id, tunnel_server, proxy_addr):
        self.id = connection_id
        conn_dest = proxy_addr if proxy_addr else tunnel_server
        self.http_conn = httplib.HTTPConnection(conn_dest['host'], conn_dest['port'])
        self.tunnel_server = tunnel_server

    def _url(self, url):
        return "http://{host}:{port}{url}".format(host=self.tunnel_server['host'], port=self.tunnel_server['port'], url=url)

    def create(self, target_address):
        params = urllib.urlencode({"host": target_address['host'], "port": target_address['port']})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/plain"}

        self.http_conn.request("POST", self._url("/" + self.id), params, headers)

        response = self.http_conn.getresponse()
        response.read()
        if response.status == 200:
            print 'Successfully create connection'
            return True 
        else:
            print 'Fail to establish connection: status %s because %s' % (response.status, response.reason)
            return False

    def send_put(self, data):
        params = urllib.urlencode({"data": data})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
        try:
            self.http_conn.request("PUT", self._url("/" + self.id), params, headers)
            response = self.http_conn.getresponse()
            response.read()
            print response.status
        except (httplib.HTTPResponse, socket.error) as ex:
            print "Error Sending Data: %s" % ex

    def send_data(self, data):
        params = urllib.urlencode({"data": data})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
        try:
            self.http_conn.request("POST", self._url("/put/" + self.id), params, headers)
            response = self.http_conn.getresponse()
            response.read()
            print response.status
        except (httplib.HTTPResponse, socket.error) as ex:
            print "Error Sending Data: %s" % ex

    def send(self, data):
        self.send_data(data)

    def receive(self):
        try: 
            self.http_conn.request("GET", "/" + self.id)
            response = self.http_conn.getresponse()
            data = response.read()
            if response.status == 200:
                return data
            else: 
                print "GET HTTP Status: %d" % response.status
                return ""
        except (httplib.HTTPResponse, socket.error) as ex:
            print "Error Receiving Data: %s" % ex
            return ""

    def send_delete_req(self):
        self.http_conn.request("DELETE", "/" + self.id)
        self.http_conn.getresponse()

    def send_close_req(self):
        try:
            self.http_conn.request("GET", "/delete/" + self.id)
            response = self.http_conn.getresponse()
            data = response.read()
            if response.status == 200:
                return data
            else:
                print "GET HTTP Status: %d" % response.status
                return ""
        except (httplib.HTTPResponse, socket.error) as ex:
            print "Error Receiving Data: %s" % ex
            return ""

    def close(self):
        self.send_close_req()


class SendToTunnelThread(object):

    """
    Thread to send data to remote host
    """
    def __init__(self, conn):
        self.http_tunnel = conn

    def clean_up_all(self):
        logging.warn("closing all sockets")
        self.http_tunnel.close()

    def send_to_tunnel(self, data):
        if data:
            logging.warn("Receive OK")
            self.http_tunnel.send(data)


class ReceiveFromTunnelThread(threading.Thread):

    """
    Thread to receive data from remote host
    """

    def __init__(self, server_sock, src_address, conn):
        threading.Thread.__init__(self, name="Receive-Thread")
        self.server_sock = server_sock
        self.src_address = src_address
        self.http_conn = conn
        self._stop = threading.Event()

    def run(self):
        while not self.stopped():
            data = self.http_conn.receive()
            if len(data) == 0:
                continue
            logging.debug(data)
            try:
                self.server_sock.sendto(data, self.src_address)
                print "sending data:", len(data)
            except:
                #Do not need to send http request here, we'll do it in sender.
                traceback.print_exc()
            logging.warn("socket send ok")

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()


class ClientWorker(threading.Thread):
    def __init__(self, server_sock, src_address, tunnel_server, target_address, proxy_address):
        threading.Thread.__init__(self)
        self.server_sock = server_sock
        self.src_address = src_address
        self.tunnel_server = tunnel_server
        self.target_address = target_address
        self.proxy_address = proxy_address
        self.connection = None
        self.sender = None
        self.receiver = None
        #generate unique connection ID
        connection_id = str(uuid4())
        #main connection for create and close
        self.connection = Connection(connection_id, self.tunnel_server, self.proxy_address)

        if self.connection.create(self.target_address):
            self.sender = SendToTunnelThread(Connection(connection_id, self.tunnel_server, self.proxy_address))
            self.receiver = ReceiveFromTunnelThread(self.server_sock, self.src_address,
                                                    Connection(connection_id, self.tunnel_server, self.proxy_address))
            self.receiver.start()

    def send_to_tunnel(self, data):
        self.sender.send_to_tunnel(data)

    def stop(self):
        #stop read and send threads
        self.receiver.stop()
        #send close signal to remote server
        self.connection.close()
        #wait for read and send threads to stop and close local socket
        self.receiver.join()


def start_tunnel(listen_port, tunnel_server, target_addr, proxy_addr):
    """Start tunnel"""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind(('', int(listen_port)))
    receive_from_tunnel_thread = None
    print "waiting for udp package"
    workers = {}
    try:
        while True:
            data, src_address = server_sock.recvfrom(BUFFER)
            print "received packet from: ", src_address, len(data)
            if src_address in workers:
                worker = workers[src_address]
            else:
                worker = ClientWorker(server_sock, src_address, remote_addr, target_addr, proxy_addr)
                workers[src_address] = worker
            worker.send_to_tunnel(data)
    except (KeyboardInterrupt, SystemExit):
        server_sock.close()
        for w in workers:
            w.stop()
        for w in workers:
            w.join()
        sys.exit()

if __name__ == "__main__":
    """Parse argument from command line and start tunnel"""

    parser = argparse.ArgumentParser(description='Start Tunnel')
    parser.add_argument('-p', default=8890, dest='listen_port',
                        help='Port the tunnel listens to, (default to 8890)', type=int)
    parser.add_argument('target', metavar='Target Address',
                        help='Specify the host and port of the target address in format Host:Port')
    parser.add_argument('-r', default='localhost:19999', dest='remote',
                        help='Specify the host and port of the remote server to tunnel to '
                             'This specify the tunnel server(Default to localhost:9999)')
    parser.add_argument('-o', default='', dest='proxy',
                        help='Specify the host and port of the proxy server(host:port)')

    args = parser.parse_args()

    target_addr = {"host": args.target.split(":")[0], "port": args.target.split(":")[1]}
    remote_addr = {"host": args.remote.split(":")[0], "port": args.remote.split(":")[1]}
    proxy_addr = {"host": args.proxy.split(":")[0], "port": args.proxy.split(":")[1]} if (args.proxy) else {}
    start_tunnel(args.listen_port, remote_addr, target_addr, proxy_addr)