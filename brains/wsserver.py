##########################
# Websocket Server with specific trol protocol additions
#
# Original Author: Johan Hanssen Seferidis
# License: MIT
# See the end of this file.
#
# like the ship of theseus it's very difficult to know if any of this code still belongs to JHS or if he'd want to claim it as his anyhow
import sys
import struct
import ssl
from base64 import b64encode
from hashlib import sha1
import logging
import errno
import threading
from socketserver import ThreadingMixIn, TCPServer, StreamRequestHandler
from socket import timeout as TimeoutError # until python 3.10 this is called "timeout" not TimeoutError because Python is a moving target
from time import time
import traceback

from thread import ThreadWithLoggedException as Thread
import json

from ipaddress import IPv4Address
from queue import SimpleQueue, Empty

log = logging.getLogger(__name__)
logging.basicConfig()

FIN    = 0x80
OPCODE = 0x0f
MASKED = 0x80
PAYLOAD_LEN = 0x7f
PAYLOAD_LEN_EXT16 = 0x7e
PAYLOAD_LEN_EXT64 = 0x7f

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT         = 0x1
OPCODE_BINARY       = 0x2
OPCODE_CLOSE_CONN   = 0x8
OPCODE_PING         = 0x9
OPCODE_PONG         = 0xA

CLOSE_STATUS_NORMAL = 1000
DEFAULT_CLOSE_REASON = bytes('', encoding='utf-8')

# How often, in seconds, roughly, to cycle in timeouts
SPIN_RATE = 1


class wsServer(ThreadingMixIn, TCPServer):
   allow_reuse_address = True
   daemon_threads = True

   def __init__(self, host='127.0.0.1', port=0, loglevel=logging.WARNING, key=None, cert=None, insecureLocal=True, clientTimeout=300):
      log.setLevel(loglevel)
      TCPServer.__init__(self, (host, port), wsHandler)
      self.host = host
      self.port = self.socket.getsockname()[1]

      self.key = key
      self.cert = cert
      self.insecureLocal = insecureLocal
      self.clientTimeout = clientTimeout

      self.callbacks = {}
      self.clients = []
      self.id_counter = 0
      self.thread = None

   def run_forever(self):
      cls_name = self.__class__.__name__
      try:
         log.info("Listening on port %d for clients.." % self.port)
         self.thread = Thread(target=super().serve_forever, daemon=True, log=log, name="Websocket Server")
         # log.info(f"Starting {cls_name} on thread {self.thread.getName()}.")
         self.thread.start()
      except KeyboardInterrupt:
         self.server_close()
         # log.info("Server terminated.")
      except Exception as e:
         log.error(str(e), exc_info=True)
         sys.exit(1)

   def finish_request(self, request, client_address):
      # We're just overriding this from the base class to change the calling signature to include the server-assigned
      # serial ID for this client.
      # Interestingly, the base class just creates handler object and returns because
      # all calls to handler functions happen in handler __init__
      self.id_counter += 1
      self.RequestHandlerClass(request, client_address, self.id_counter, self)

   def set_callback(self, cb_name, cb_func):
      self.callbacks[cb_name] = cb_func

   # client_auth called first, early after socket connection established and headers read into client.headers
   def client_auth(self, client):
      if('client_auth' in self.callbacks):
         return self.callbacks['client_auth'](client, self)
      return False

   # client_connected called "last", after successful websocket handshake, ready to start regular client use.
   def client_connected(self, client):
      self.clients.append(client)
      if('client_connected' in self.callbacks):
         self.callbacks['client_connected'](client, self)

      log.info(f"Client {client.id}({client.user}) connected.")

   # client_disconnected called when another one bites the dust
   def client_disconnected(self, client):
      try:
         if('client_disconnected' in self.callbacks):
            self.callbacks['client_disconnected'](client, self)
      finally:
         if client in self.clients:
            self.clients.remove(client)

      log.info(f"Client {client.id}({client.user}) disconnected.")

   def client_message(self, client, mtype, message):
      log.debug(f"Client {client.id} sent mtype: {mtype}");
      if('client_message' in self.callbacks):
         handled = self.callbacks['client_message'](client, self, mtype, message)
         if not handled:
            pass # TODO: IDK something maybe
      else:
         log.warning("What am I supposed to do with this?")

   # TODO: add flag option to only send to users who have a certain flag set, e.g. 'camusers' and make the send_to_list in tb2 obsolete
   # this means ws knows more specifica bout trol protocol but it's already mixed up in the messaging with client_message and knowing mtypes
   def send_message_to_all(self, mtype, message, but=None):
      for c in self.clients:
         if(c.keep_alive and c != but):
            c.send_message(mtype, message)

   def shutdown_gracefully(self, status=CLOSE_STATUS_NORMAL, reason=DEFAULT_CLOSE_REASON):
      self.keep_alive = False
      # Send CLOSE to clients
      for c in self.clients:
        c.send_close(status, reason)
      self.shutdown_abruptly()

   def shutdown_abruptly(self):
      self.keep_alive = False
      for c in self.clients:
         c.keep_alive = False

      self.server_close()
      self.shutdown()


# "handler" really means client and since we're rolling with threads all this is created from the client's thread.
# in fact in a real oddness the StreamRequestHandler.__init__ doesn't return during the objects lifecycle, instead 
# it calls .setup() .handle() .finish() itself -- in the "constructor."  This is a Python paradigm I guess?  Very interesting.
class wsHandler(StreamRequestHandler):

   def __init__(self, socket, addr, client_id, server):
      self.sendqueue = SimpleQueue()
      self.timeout = SPIN_RATE
      self.clientTimeout = server.clientTimeout
      self.id    = client_id
      self.user   = "Unknown"
      self.keep_alive = True
      self.handshake_done = False
      self.valid_client = False
      self.lastactivetime = time()

      threading.current_thread().name = f"Client Handler {self.id}"
      self.send_thread = Thread(target=self.send_thread_worker, daemon=True, log=log, name=f"Client Send Thread {self.id}")
      self.send_thread.start()

      # self.* below should be provided by super call
      # self.client_address = addr
      # self.server      = server
      # self.request      = socket

      if server.cert:
         if IPv4Address(addr[0]).is_private and server.insecureLocal:
            # log.debug(f"Expecting insecure ws:// for {addr[0]}")
            pass
         else:
            # log.debug(f"Expecting secure wss:// for {addr[0]}")
            try:
               socket = ssl.wrap_socket(socket, server_side=True, certfile=server.cert, cert_reqs=ssl.CERT_NONE, ssl_version=ssl.PROTOCOL_TLS)
            except Exception as e: # Not sure which exception it throws if the key/cert isn't found
               log.warning(f"SSL not available {e}")
               raise 

      # We set socket timeout to a short value here but we'll check 
      # the server.clientTimeout value in the read loop below
      socket.settimeout(SPIN_RATE)

      StreamRequestHandler.__init__(self, socket, addr, server)

   def send_thread_worker(self):
      # This method is run from a separate thread and just services the queue of data to be sent out
      # TODO: Properly implement client timeout as in read_bytes 
      while self.keep_alive:
         # tfin = time() + self.clientTimeout
         try:
            tosend = self.sendqueue.get(block=True,timeout=SPIN_RATE)
            self.request.sendall(tosend)
         except Empty:
            # log.debug(f"Client {self.id} internal send timeout")
            pass
         except Exception as e:
            log.error(f"Client {self.id} dying because send failed: {e}")
            self.keep_alive = False

   # setup() -> handle() -> finish() object lifetime
   def setup(self):
      super().setup()   # I believe this is documented as creating self.rfile which self.handshake needs
                        # TODO: Make above comment false by removing all use of rfile.
      # websock protocol includes a bizarre little challenge-response handshake to begin
      assert not self.handshake_done, "Obviously we just got here."
      self.handshake()

   def handle(self):
      # now we just read incoming messages until the threads come home
      try:
         while self.keep_alive:
            self.read_next_message()
            self.lastactivetime = time()
      except Exception as e:
         log.warning(f"{self.id}({self.user}) read handler caught exception: " + traceback.format_exc())
         self.keep_alive = False
      # We don't need to explicitly call finish() here, it's in a finally: clause already in the super class
      # that happens right after handle() returns
      # log.debug(f"{self.id} read finished.")

   def finish(self):
      # TODO: Is this the right way to finish the send thread?
      # log.debug(f"{self.id} handler finishing...")
      self.keep_alive = False
      self.server.client_disconnected(self)
      self.send_thread.join()
      # log.debug(f"{self.id} handler finished.")

   def read_bytes(self, num):
      ba = bytearray(0)
      tfin = int(time()) + self.clientTimeout
      # remember: all socket operations have a timeout set in __init__ and we have to add those
      # together until we reach the client idle timeout in self.timeout which is typically *much* longer
      while(len(ba) < num):
         try:
            # use self.rfile.read() and stuff gets WEIRD; we timeout after X seconds 
            # (that's by design) then catch the TimeoutError (actually a timeout, see imports)
            # then loop back here and call self.rfile.read() again expecting to sit another X seconds
            # but INSTEAD it immediately fails with an OSError "cannot read from timed out object"
            # the code seems to be written so that if there is a time out error ever the object becomes 
            # unreadable forever... what? I can't even ... Python why
            b = self.request.recv(num - len(ba))
            # log.debug(f"read {len(ba)} of {num} bytes")
            ba.extend(b)
         except TimeoutError as e: 
            if(int(time()) > tfin):
               # log.debug(f"Full timeout for {self.id}")
               raise TimeoutError(f"client {self.id} exceeded read timeout")
            #log.debug(f"Internal timeout for {self.id} with " + str(tfin - int(time())) + "s remaining")
            if(not self.keep_alive):
               # log.debug(f"Client {self.id} read_bytes returning because keep_alive is false")
               raise Exception(f"Client {self.id} read_bytes returning because keep_alive is false")
      # log.debug(f"returning {len(ba)} of {num} bytes")
      return ba

   def read_next_message(self):
      try:
        b1, b2 = self.read_bytes(2)
      except Exception as e: 
        b1, b2 = 0, 0
        log.info(type(e).__name__ + f" Exception for client {self.id} {e}")
        self.keep_alive = False
        return

      fin   = b1 & FIN
      opcode = b1 & OPCODE
      masked = b2 & MASKED
      payload_length = b2 & PAYLOAD_LEN

      if opcode == OPCODE_CLOSE_CONN:
        log.info(f"Client {self.id} sent close request.")
        self.keep_alive = False
        return
      if not masked:
        log.warning(f"Client {self.id} data not masked.")
        self.keep_alive = False
        return
      if opcode == OPCODE_CONTINUATION:
        log.warning(f"Client {self.id} used unsupported websocket function.")
        self.keep_alive = False
        return
      elif opcode == OPCODE_BINARY:
        log.warning(f"Client {self.id} used unsupported websocket function.")
        self.keep_alive = False
        return
      elif opcode == OPCODE_TEXT:
        opcode_handler = self.message_received
      elif opcode == OPCODE_PING:
        opcode_handler = self.ping_received
      elif opcode == OPCODE_PONG:
        opcode_handler = self.pong_received
      else:
        log.warning(f"Client {self.id} sent opcode {opcode}")
        self.keep_alive = False
        return

      # TODO: we should checkl to be sure exceptions raised in read_bytes calls below are handled appropriately
      if payload_length == 126:
        payload_length = struct.unpack(">H", self.read_bytes(2))[0]
      elif payload_length == 127:
        payload_length = struct.unpack(">Q", self.read_bytes(8))[0]

      masks = self.read_bytes(4)
      message_bytes = bytearray()
      for message_byte in self.read_bytes(payload_length):
        message_byte ^= masks[len(message_bytes) % 4]
        message_bytes.append(message_byte)
      # Call to handler delayed from above opcode switch
      opcode_handler(message_bytes.decode('utf8'))

   # send_message and message_received both deal with our special
   # trol message format, which as of this writing is just a json string
   # containing a dictionary which has at least one key named mtype
   def send_message(self, mtype, mdata):
      if(not self.keep_alive):
         # TODO: OK so we have this problem, actually a problem in reading data, not sending, I think, where it never times out on reads and
         # we somehow never kill the client, since it's the read thread responsible for that.  I think.  One way or another, some clients
         # get "hung up" and the log fills up with "DEAD TO US" messages above because we're never getting them out of the client list 
         # in the server object
         # I've played with it a little but until I have time to solve it, we can just "reboot" ourselves by suiciding and letting systemd resurrect us
         # we'll pick an arbitary number of times we get here before we kill ourselves by CTRL-C

         if not self.keepalivecount:
            self.keepalivecount = 0
         self.keepalivecount += 1

         log.warning(f"{self.id} can't get messages because they're DEAD TO US (x{self.keeepalivecount}).")
         if self.keepalivecount > 50:  # completely arbitrary
            raise KeyboardInterrupt

         return
      if(not mdata):
         log.warning(f"{self.id} tried to send {mtype} with no data")
      mdata['mtype'] = mtype
      self.send_text(json.dumps(mdata))

   def message_received(self, message):
      mtype = None
      mdata  = None
      try: 
         mdata = json.loads(message)
         mtype = mdata['mtype']
      except Exception as e:
         log.warning(f"{self.id} bad message format {e}: {message}")
         self.keep_alive = False
         
      self.server.client_message(self, mtype, mdata)

   # These pings and pongs are defined in the websocket standard.  We don't use them and neither does anyone else.
   # Also we might have broken them because if we turn them on in trolbot we get exceptions and I can't be bothered
   def ping_received(self, message):
      log.debug(f"Client {self.id} sent ping; responding.")
      self.send_text(message, OPCODE_PONG)

   def pong_received(self, message):
      log.debug(f"Client {self.id} sent pong; did we ask for that?")
      pass

   def send_close(self, status=CLOSE_STATUS_NORMAL, reason=DEFAULT_CLOSE_REASON):
      if status < CLOSE_STATUS_NORMAL or status > 1015:
        raise Exception(f"CLOSE status must be between 1000 and 1015, got {status}")

      header = bytearray()
      payload = struct.pack('!H', status) + reason
      payload_length = len(payload)
      assert payload_length <= 125, "keep it brief"

      # Send CLOSE with status & reason
      header.append(FIN | OPCODE_CLOSE_CONN)
      header.append(payload_length)

      self.sendqueue.put(header + payload)

   # Doesn't actually send anything now that we have a separate send thread, just enqueues for sending.
   def send_text(self, message, opcode=OPCODE_TEXT):
      # Validate message
      if isinstance(message, bytes):
        try:
           message = message.decode('UTF-8')
        except UnicodeDecodeError:
           log.warning("Can\'t send message, message is not valid UTF-8")
           return False
      elif not isinstance(message, str):
        log.warning('Can\'t send message, message has to be a string or bytes. Got %s' % type(message))
        return False

      header  = bytearray()
      payload = None
      try:
         payload = message.encode('UTF-8')
      except UnicodeEncodeError as e:
         log.error(f"Could not encode data to UTF-8: {e}")
         return False

      payload_length = len(payload)

      if payload_length <= 0 and opcode != OPCODE_TEXT: # It's probably OK to do OPCODE_PONG without a message but why do I care we don't use that.
         log.error("send_text called with no message")
         return False

      # Normal payload
      if payload_length <= 125:
        header.append(FIN | opcode)
        header.append(payload_length)

      # Extended payload
      elif payload_length >= 126 and payload_length <= 65535:
        header.append(FIN | opcode)
        header.append(PAYLOAD_LEN_EXT16)
        header.extend(struct.pack(">H", payload_length))

      # Huge extended payload
      elif payload_length < 18446744073709551616:
        header.append(FIN | opcode)
        header.append(PAYLOAD_LEN_EXT64)
        header.extend(struct.pack(">Q", payload_length))

      else:
        raise Exception("Message is too big. Consider breaking it into chunks.")
        return

      self.sendqueue.put(header + payload)

   def read_http_headers(self):
      self.headers = {}
      # first line should be HTTP GET
      # TODO:
      # self.rfile has issues (see read_bytes) and this should be using self.request which is a socket
      # but that's for another day.
      self.httpreq = self.rfile.readline().decode().strip().split()
      assert self.httpreq[0] == 'GET', f"Client {self.id} incorrect request type: {self.httpreq[0]}"

      # remaining should be headers
      while True:
        # TODO: rfile considered harmful
        header = self.rfile.readline().decode().strip()
        if not header:
           break
        head, value = header.split(':', 1)
        self.headers[head.lower().strip()] = value.strip()
      return self.headers

   def handshake(self):
      headers = self.read_http_headers()

      try:
         assert self.server.client_auth(self)
      except Exception as e:
         self.keep_alive = False
         log.warning(f"Client {self.id} auth failure: {e}")
         return

      try:
         assert headers['upgrade'].lower() == 'websocket'
         key = headers['sec-websocket-key']
      except Exception as e:
         log.warning(f"Client {self.id} protocol failure: {e}")
         self.keep_alive = False
         return

      self.sendqueue.put(self.make_handshake_response(key).encode())
      self.handshake_done = True
      self.server.client_connected(self)

   @classmethod
   def make_handshake_response(cls, key):
      return \
       'HTTP/1.1 101 Switching Protocols\r\n'\
       'Upgrade: websocket\r\n'          \
       'Connection: Upgrade\r\n'         \
       'Sec-WebSocket-Accept: %s\r\n'      \
       '\r\n' % cls.calculate_response_key(key)

   @classmethod
   def calculate_response_key(cls, key):
      GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
      hash = sha1(key.encode() + GUID.encode())
      response_key = b64encode(hash.digest()).strip()
      return response_key.decode('ASCII')


def encode_to_UTF8(data):
   try:
      return data.encode('UTF-8')
   except UnicodeEncodeError as e:
      log.error(f"Could not encode data to UTF-8: {e}")
      return False

#The MIT License (MIT)
#
#Copyright (c) 2018 Johan Hanssen Seferidis
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in all
#copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#SOFTWARE.
