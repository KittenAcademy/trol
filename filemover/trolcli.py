#!/usr/bin/python3 -u
import asyncio
import json
import os
import sys
import pathlib
import websockets
from traceback import format_exc
import argparse

async def wsinform(wsurl, fn):
   # print(f"Connecting to {wsurl}")
   async with websockets.connect(wsurl, ping_interval=None) as w:
      # print("Connected to trol")

      async def send_to_trol(mtype, message):
         message['mtype'] = mtype;
         await w.send(json.dumps(message))

      await send_to_trol("user.hello", { "user": "cli" })
      await send_to_trol("recording.created", { "filename": fn })

if __name__ == "__main__":
   ap = argparse.ArgumentParser()
   ap.add_argument('-W', '--wsurl', help="URL of trolbot websocket", default="ws://localhost:8081")
   ap.add_argument('filename')
   args=ap.parse_args()
   
   asyncio.run(wsinform(args.wsurl, args.filename))
   sys.exit(0)

