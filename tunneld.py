#!/usr/bin/env python
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import logging
import socket
import cgi
import argparse

socket.setdefaulttimeout(10)


class ProxyRequestHandler(BaseHTTPRequestHandler):

    sockets = {}
    target_addresses = {}
    BUFFER = 1024 * 50 

    def _get_connection_id(self):
        return self.path.split('/')[-1]

    def _get_operation(self):
        return self.path.split('/')[-2]

    def _get_socket(self):
        """get the socket which connects to the target address for this connection"""
        id = self._get_connection_id()
        return self.sockets[id] 

    def _close_socket(self):
        """ close the current socket"""
        id = self._get_connection_id()
        s = self.sockets[id]
        if s:
            s.close()
            del self.sockets[id]

    def handle_get_req(self, id):
        s = self.sockets.get(id, None)
        if s:
            print 'GET data'
            try:
                data, address = s.recvfrom(self.BUFFER)
                print "data received:", len(data)#, data
                logging.debug(data)
                self.send_response(200)
                self.end_headers()
                if data:
                    self.wfile.write(data)
            except socket.timeout:
                print 'Connection Timeout'
                self.send_response(504)
                self.end_headers()
            except socket.error as ex:
                print 'Error getting data from target socket: %s' % ex
                self.send_response(503)
                self.end_headers()
        else:
            print 'Connection With ID %s has not been established' % self._get_connection_id()

    def do_GET(self):
        """GET: Read data from TargetAddress and return to client through http response"""
        id = self._get_connection_id()
        operation = self._get_operation()
        if operation == "delete":
            self.handle_close_req()
        else:
            self.handle_get_req(id)

    def handle_post_request(self, id):
        print 'Initializing connection with ID %s' % id
        length = int(self.headers.getheader('content-length'))
        req_data = self.rfile.read(length)
        params = cgi.parse_qs(req_data, keep_blank_values=1)
        target_host = params['host'][0]
        target_port = int(params['port'][0])
        self.target_addresses[id] = (target_host, target_port)
        print 'Connecting to target address: %s % s' % (target_host, target_port)
        # open socket connection to remote server
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #s.connect((target_host, target_port))
        #s.settimeout(7)
        print 'Successfully created'
        #save socket reference
        self.sockets[id] = s
        try:
            self.send_response(200)
            self.end_headers()
        except socket.error, e:
            print e

    def do_POST(self):
        """POST: Create TCP Connection to the TargetAddress"""
        id = self._get_connection_id()
        operation = self._get_operation()
        if operation == "put":
            self.handle_put_request()
        else:
            self.handle_post_request(id)

    def handle_put_request(self):
        id = self._get_connection_id()
        s = self.sockets[id]
        length = int(self.headers.getheader('content-length'))
        data = cgi.parse_qs(self.rfile.read(length), keep_blank_values=1)['data'][0]
        print 'Writing....', len(data)#, data
        logging.debug(data)
        try:
            #s.sendall(data)
            s.sendto(data, self.target_addresses[id])
            self.send_response(200)
        except socket.timeout:
            print 'Connection Timeout'
            self.send_response(504)
        except socket.error as ex:
            print 'Error sending data from target socket: %s' % ex
            self.send_response(503)
        self.end_headers()

    def do_PUT(self):
        """Read data from HTTP Request and send to TargetAddress"""
        self.handle_put_request()

    def handle_close_req(self):
        self._close_socket()
        self.send_response(200)
        self.end_headers()

    def do_DELETE(self):
        self.handle_close_req()


def run_server(port, server_class=HTTPServer, handler_class=ProxyRequestHandler): 
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    httpd.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Tunnel Server")
    parser.add_argument("-p", default=19999, dest='port', help='Specify port number server will listen to', type=int)
    args = parser.parse_args()
    run_server(args.port)
