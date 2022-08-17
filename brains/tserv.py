#!/usr/bin/python3
############################
# Seriously, IDK why I have this layer in here.
#
# Why does this file exist?  WHY
# Does this need to be in-between tb and wsserver?
# Maybe I originally planned to keep anything trol-specific out of wsserver?
############################
import argparse
import logging

import json

from wsserver import wsServer
from ipaddress import IPv4Address

server  = None
log     = None
mtypes  = {}

# CALLBACK FOR WEBSOCKET
def auth_client(client, server):
    if(IPv4Address(client.client_address[0]).is_private):
       log.info(f"Allowing Client {client.id} from local {client.client_address[0]}")
       client.islocal = True
       client.user = 'HOUSE'
       return True

    client.islocal = False
    log.warning(f"Disallowing {client.id} from {client.client_address[0]}")
    raise Exception("Client {client.id} failed auth.")

# CALLBACK FOR WEBSOCKET
def message_received(client, server, mtype, mess):
   if mtype not in mtypes:
      log.warning(f"{client.id} invalid mtype: {mtype}")
      return
   # dispatch via mtypes callbacks 
   mtypes[mtype](client, mess)

def create_server(*args, **kwargs):
   global log, server
   # Set up logging
   logging.basicConfig()
   log = logging.getLogger('tserv')
   log.setLevel(kwargs.get('loglevel', logging.DEBUG))

   server = wsServer(*args, **kwargs)
   server.set_callback("client_auth", auth_client)
   # server.set_callback("client_connected", new_client)
   # server.set_callback("client_disconnected", )
   server.set_callback("client_message", message_received)
   return server

def start_server():
   server.run_forever()
   log.info(f"trolbrains server started")

def close_server():
   server.thread.join()
   server.server_close()

def register_message(mtype, callback):
   global mtypes
   mtypes[mtype] = callback

