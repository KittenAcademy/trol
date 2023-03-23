#!/usr/bin/python3 
###########################
# trolbot.py
#
# Discord bot that connects to trol system.  
# 
###########################
import configparser
import discord
from discord.ext import commands
import websockets
import asyncio
import json
import argparse
import logging
import re
from time import time,localtime
from datetime import timedelta
from traceback import format_exc

# To manipulate camera thumbnails
import imageio.v3 as iio
from base64 import b64decode
from io import BytesIO

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('discord').setLevel(logging.WARN)
logging.getLogger('websockets').setLevel(logging.INFO)
log = logging.getLogger('trolbot')
log.setLevel(logging.DEBUG)

# Get config
conf = None
try:
   aparse = argparse.ArgumentParser()
   aparse.add_argument('-c', '--config', help='config file', default='./discord.conf')
   aparse.add_argument('--wsurl', help='override ws url')
   args = aparse.parse_args()

   conf = configparser.ConfigParser()
   conf.read(args.config)
except Exception as e:
   log.critical(f"Cannot: {e}") 
   aparse.print_usage()
   exit()


# bot object is Discord
bot = commands.Bot(command_prefix='$')
# ws object is Trol websocket
ws = None
# state memory for Trol
camlist     = {}
scenedata   = None
activescene = None
poslist     = {}

# Handles communication from the WebSocket/trol
async def handle_message(mess):
   global camlist, scenedata, activescene, poslist
   item = {}
   try:
      item=json.loads(mess)
   except:
      log.warning("Badly-formatted message from server: " + mess)
      return

   mtype = item.get('mtype')
   if(not mtype):
      log.warning(f"Got message without mtype: {mess}")
      return

   if mtype == "server.ping": # Server warning us to say something or be killed
      await send_to_trol("user.pong", { "time": time() })
   elif mtype == "recording.created":
      await poll_recording_label(item.get('filename'), duration=7200)
   # News Messages
   elif mtype == "news.data": # This is the one we get if we requested the data specifically
      await handle_listNews(item.get('newsdata'))
   elif mtype == "news.setscrolldata": # This is the one we get whenever anyone changes news data
      await handle_listNews(item.get('newsdata'))
   elif mtype == "news.showscrolldata": # This is the one we get when the news scroll is activated
      pass
   # Magic Cam Indicator?  Should be better.
   elif mtype == "request.recording": # Used as a signal of whether the magic cam is on
      # should more properly maybe be xsplit.recording which is what's sent when actually recording but it's not passed through trol yet
      lt = localtime(time())
      t = f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}"
      isactive = "started" if item.get("record", False) else "ended"
      await send_to_channel(f"Recording {isactive} at {t}")
   # Messages we need for displaying thummnails on chat
   elif mtype == "server.camlist": 
      # For truly no good reason the camlist comes as an array so we put it in a dictionary by name
      # Also for truly no good reason the thumbs sent with the camlist are tuples of (time, data)
      # whereas the ones we're sent 'live' are just the data.  So that's all we keep here.
      cl = item.get("cams")
      for c in cl:
         t = [];
         for th in c['thumbs']:
            t.append(th[1])
         c['thumbs'] = t
         camlist[c['name']] = c
   elif mtype == "xsplit.scenedata":
      scenedata = item.get("scenedata")
   elif mtype == "xsplit.scenechanged":
      activescene = item.get("scene")
   elif mtype == "xsplit.positionchanged":
      p = item.get("pos")
      c = item.get("cam")
      poslist[p] = c
      cstr = f"camera {c}"
      if("PUBLIC" not in camlist[c]['flags']):
         cstr = "unknown camera"
      await send_to_channel(f"Position {p} now showing {cstr}", filedata=create_gif(camlist[c]["thumbs"]), filename=cstr, duration=60)
   elif mtype == "camera.thumb":
      c = item.get("name")
      camlist[c]["thumbs"].insert(0, item.get("data")) 
      del camlist[c]["thumbs"][3:]
   elif mtype == "user.error":
      # TODO: Once we start tracking users properly, make sure this message goes to whoever made the request.
      await send_to_channel(f"There was an error: {item.get('errmsg')}")
   elif mtype == "server.activerotations":
      pass # for now
   else:
      log.warning(f"Got unknown mtype: {mtype}")

async def announce_and_set_winner(pitem, pos, channel):
   winner = pitem['name']
   if winner == 'Currently Displayed':
      await send_to_channel(f"Let it ride!", channel=channel)
      return
   
   await send_to_channel(f"The winner of the poll is: {pitem['name']}", channel=channel)
   await send_to_trol("request.positionchange", { "pos": pos, "cam": pitem['name'] } )


# TODO: Set up an automatic poller to get camera changes all night long
# TODO: Prevent anyone from setting positions we don't want set
# TODO: discord.py can inform of when reactions are added instead of us waiting and polling afterwards, which might allow for interesting feedback and
# an option like switch cameras after 30 seconds or 5 votes, whichever is first.
async def create_poll(pdata, callback=announce_and_set_winner, duration=30, cdata=None, channel=conf['general']['channel']):
   # pdata = list of items to select from in the poll.  each one has a 'name', 'filedata' = imagedata, 'filename' = optional.
   await send_to_channel(f"Vote for one of the following by clicking the first emoji reaction under your selection.  You have {duration} seconds to choose.  If no one votes, the current camera will remain.", duration=duration, channel=channel)

   for pitem in pdata:
      n = pitem.get('name', None)
      fd = pitem.get('filedata', None)
      fn = pitem.get('filename', None)
      currentposlist = pitem.get('currentposlist', None)
      if(n is None and fd is None):
         log.warn(f"Attempt to poll with item missing data")
         continue
      text = n + (f" (already displayed in position {','.join(currentposlist)})" if currentposlist else "")
      # Let's not automatically delete the messages here, do that when reading out the results so we don't step on ourselves.
      postedmessage = await send_to_channel(text, filedata=fd, filename=fn, channel=channel)
      pitem['posted'] = postedmessage
      await postedmessage.add_reaction('\u2b06') # Unicode up arrow

   async def return_results():
      try:
         await asyncio.sleep(duration)
         votes = 0
         winner = None
         for pitem in pdata:
            pm = discord.utils.get(bot.cached_messages, id=pitem.get('posted').id)
            if pm is None:
               log.warning("Poll item " + pitem.get('name') + " message missing?")
               await send_to_channel("Poll aborted because messages were deleted too quickly.", channel=channel, duration=duration)
               return pdata[0]
            rcount = len(pm.reactions)
            if(not rcount > 0):
               log.warning("Poll item " + pitem.get('name') + " reactions missing?")
               continue
            v = pm.reactions[0].count
            if v > votes:
               votes = v
               winner = pitem
            bot.loop.create_task(pm.delete())
         if winner is None:
            winner = pdata[0]
         await callback(winner, cdata, channel)
         return winner
      except asyncio.CancelledError:
         log.debug(f"Waiting on poll results cancelled.")
         return pdata[0]

   return bot.loop.create_task(return_results())
      

async def handle_listNews(i):
   if(len(i) == 0):
      return
      # message += "No news items.\n"

   message = "Here's the current news items:\n\n"

   for n in i:
      lt = localtime(n['expires'])
      remainingTime = n['expires'] - time();
      rt = timedelta(seconds=remainingTime)
      message += f"{n['id']} (Expires on {lt.tm_mon}-{lt.tm_mday} at {lt.tm_hour:02d}:{lt.tm_min:02d}): {n['message']}\n"

   await send_to_channel(message)

def create_gif(imgdat):
   if(len(imgdat) == 0):
      return None
   try:
      imgs = []
      for d in reversed(imgdat): # Because new frames of thumbnails go into index 0
         imgs.append(iio.imread(b64decode(d.removeprefix("data:image/jpg;base64,")), extension=".jpg"))
      
      return BytesIO(iio.imwrite("<bytes>", imgs, extension=".gif", duration=1000, loop=0))
   except:
      log.warn(format_exc())

   return None
      

async def poll_recording_label(filename, duration=300, channel=conf['general']['channel']):

   fn = re.split("/", filename)[-1]
   tp = re.split("[_.-]", fn)
   rectime = f"{tp[0]}-{tp[1]}-{tp[2]} {tp[3]}:{tp[4]}:{tp[5]}"
   log.debug(f"Polling for recording {filename} with timestamp {rectime}")

   pollmsg = await send_to_channel(
      f"I've detected a new recording/micro closeup that ended at {rectime}.  " +
      f"Please help me label it.  You can reply to this message with a short description. \n" +
      f"TIP: use names wherever possible, e.g. \"Custard playing with Sailing Kits\" not \"Faculty playing with kittens.\" \n" +
      f"If there are multiple replies, the reply with the most reactions will be selected. \n " +
      f"IMPORTANT: If this is not a micro closeup (like if it's a mailbag or a live closeup), please do not reply.  Instead click the 'no' emoji below. \n" +
      f"You have {duration/60} minutes:", channel=channel)
   await pollmsg.add_reaction('\u26d4') # Unicode 'no entry'

   replies = []

   async def get_replies(message):
      nonlocal replies
      # log.debug(f"Got message: {message.clean_content}")
      if message.reference and message.reference.message_id == pollmsg.id:
         # log.debug(f"Got reply: {message.clean_content}")
         replies.append(message)
   bot.add_listener(get_replies, name="on_message")

   async def get_results():
      await asyncio.sleep(duration)
      bot.remove_listener(get_replies, name="on_message")
      pm = discord.utils.get(bot.cached_messages, id=pollmsg.id)
      try:
         if pm is None:
            raise Exception("Missing pollmsg")
         rcount = len(pm.reactions)
         if(not rcount > 0):
            raise Exception("Missing reactions")

         favorite = None
         fvotes = 0
         for r in replies:
            # log.debug(f"read reply: {r.clean_content}")
            tvotes = 0
            for react in r.reactions:
               tvotes = tvotes + react.count
            if favorite is None or fvotes < tvotes:
               favorite = r
               fvotes   = tvotes
         votesforfavorite = fvotes

         votesforpm = -1
         for react in pm.reactions:
            votesforpm = votesforpm + react.count

         isCloseup = True if votesforpm > votesforfavorite else False

         if favorite is None:
            winner = f"Recorded at {rectime}KATZ"
         else:
            winner = discord.utils.remove_markdown(favorite.clean_content)

         if isCloseup:
            await send_to_channel(f"You decided the recording wasn't a micro, so I'll leave it out of the archive.", channel=channel, duration=30)
         else:
            await send_to_channel(f"You decided the recording should be labeled \"{winner}\".", channel=channel, duration=30)
         await send_to_trol("recording.description", { 'filename': filename, 'description': winner, 'notmicro': isCloseup })

      except Exception as e:
         log.warning(f"Attempt to label {filename} resulted in exception {e}")
         await send_to_channel(f"...aborted attempt to label recording {rectime}.", channel=channel, duration=30)
      finally:
         if pm is not None:
            bot.loop.create_task(pm.delete())

   bot.loop.create_task(get_results())
 

async def send_to_trol(mtype, message):
   # TODO: Check values or IDK, anything
   message['mtype'] = mtype;
   await ws.send(json.dumps(message))

async def wsgo():
   retries = 0   
   while(True):
      try:
         wsurl = args.wsurl or conf['general']['wsurl']
         log.info(f"Connecting to {wsurl}")
         async with websockets.connect(wsurl, ping_interval=None) as w:
            global ws 
            ws = w
            if(retries > 0):
               await send_to_channel(f"I'm reconnected after {retries} attempt(s).")
               log.info(f"Reconnected to websock after {retries} attempt(s).")
               retries = 0
            else:
               await send_to_channel("I'm back!")
               log.info("Connected to websock")
            
            await send_to_trol("user.hello", { "user": "trolbot", "news": True, "cams": True, "thumbs": True })

            #####################
            # Loop here forever #
            #####################
            async for m in ws:
               await handle_message(m)

      except Exception as e:
         # log.debug("WebSock exception {e}")
         log.debug(format_exc())

      retries += 1
      log.info(f"WebSocket lost, retry {retries}...")
      if(retries == 1):
         await send_to_channel("I've lost my connection.")
      
      await asyncio.sleep(5)

def onlyChannel():
   def predicate(ctx):
      if(ctx.channel.id == int(conf['general']['channel'])):
         return True
      log.debug(f"message channel is {ctx.channel.id} but we expect {conf['general']['channel']}")
      return False
   return commands.check(predicate)

def trolRol():
   def predicate(ctx):
      for r in ctx.author.roles:
         if r.name == 'trol user':
            return True
      log.info(f"Trol role check fail.")
      return False
   return commands.check(predicate)


async def send_to_channel(message, channel=conf['general']['channel'], filedata=None, filename="unknown", duration=None):
   global bot
   await bot.wait_until_ready() # Just in case we're called too soon.

   c = bot.get_channel(int(channel))
   if(c is None):
      log.warn(f"Called send_to_channel with nonexistant channel id: {channel}")
      return

   if(filedata is not None):
      return await c.send(message, file=discord.File(filedata, filename=filename+".gif"), delete_after=duration)

   return await c.send(message, delete_after=duration)
   
@bot.command()
@onlyChannel()
@trolRol()
async def ping(ctx):
   log.debug("Got ping")
   await ctx.send('pong')

def int_maybe(m,q = None):
   """Check if first word in string m is an int, if so strip and return it, else return default param q"""
   if m is None: 
      return (m,q)

   try:
      s = m.split(maxsplit=1)
      if(len(s) > 0):
         q = int(s[0])
      else:
         m = None
      if(len(s) > 1):
         m = s[1]
      else:
         m = None
   except Exception as e:
      # We just pretend all exceptions mean we're done.
      pass

   return (m,q)
   
@bot.command()
@trolRol()
async def testcamvote(ctx, pos):
   chanid = ctx.channel.id
   if not chanid:
      log.error(f"ctx doesn't include channel ID of request, can't do anything. {ctx}");
      return
   currentcam = poslist[pos]
   if not currentcam:
      log.warning(f"No current camera for poll.")
      await send_to_channel("I just can't though.", duration=30, channel=chanid)
      return
   if 'PUBLIC' not in camlist[currentcam]["flags"]:
      await send_to_channel("Warning: The current camera is unlisted.  If you vote to switch cameras you will not be able to vote to switch back.")
   pdata = [{'name': 'Currently Displayed', 'filename': 'Current.gif', 'filedata': create_gif(camlist[currentcam]["thumbs"])}]
   for cname in camlist:
      if 'PUBLIC' not in camlist[cname]['flags']:
         continue
      if cname == currentcam:
         continue
      currentposlist = [pos for pos, cam in poslist.items() if cam == cname]
      pdata.append({'name': cname, 'filename': cname + '.gif', 'filedata': create_gif(camlist[cname]["thumbs"]), 'currentposlist': currentposlist })
   resultTask = await create_poll(pdata, cdata=pos, channel=chanid)

@bot.command()
@trolRol()
async def testlabelvote(ctx, fn, duration=20):
   chanid = ctx.channel.id
   if not chanid:
      log.error(f"ctx doesn't include channel ID of request, can't do anything. {ctx}");
      return
   
   await poll_recording_label(fn, channel = chanid, duration=300)

@bot.command()
@trolRol()
async def camchange(ctx, pos, cam):
   chanid = ctx.channel.id
   if not chanid:
      log.error(f"ctx doesn't include channel ID of request, can't do anything. {ctx}");
      return
   try:
      currentcam = poslist[pos]
      if not currentcam:
         raise Exception("no current camera in position {pos} ?")
      if 'PUBLIC' not in camlist[cam]["flags"]:
         raise Exception(f"Attempt to set non-public camera {cam}")
      await send_to_trol("request.positionchange", { "pos": pos, "cam": cam } )
   except Exception as e:
      log.warning(f"Got exception {e} attempting camera change")
      await send_to_channel("I just can't though.", duration=30, channel=chanid)

@bot.command()
@trolRol()
async def camcheck(ctx, camid):
   chanid = ctx.channel.id
   if not chanid:
      log.error(f"ctx doesn't include channel ID of request, can't do anything. {ctx}")
      return
   try:
      if camid not in camlist:
         raise Exception(f"{camid} does not exist")
      cam = camlist[camid]
      if 'PUBLIC' not in cam["flags"]:
         raise Exception(f"{camid} is not public")
      currentposlist = [pos for pos, c in poslist.items() if c == camid]
      message = camid + (f" (currently in positions {','.join(currentposlist)})" if currentposlist else "")
      await send_to_channel(message, filedata=create_gif(cam["thumbs"]), filename=f"camera {camid}", duration=30)
   except Exception as e:
      log.warning(f"Got exception {e} attempting camera check")
      await send_to_channel("I just can't though.", duration=30, channel=chanid)

@bot.command()
@onlyChannel()
@trolRol()
async def addnews(ctx, *args):
   m = discord.utils.remove_markdown(ctx.message.clean_content).removeprefix(r"$addnews").strip()
   (m,q) = int_maybe(m,12)
   log.debug(f"Addnews from {ctx.author.name} expiring in {q} hours: '{m}'")
   if m is not None:
      await send_to_trol("news.add", {'requestingUser': ctx.author.name, 'message': m, 'expires': q})

@bot.command()
@onlyChannel()
@trolRol()
async def newsexpire(ctx, newsid, expire = 12):
   try:
      expire = int(expire)
      newsid = int(newsid)
   except Exception as e:
      log.warning(f"newsexpire params {newsid}, {expire} failed with {e}")
      pass

   log.debug(f"Newsexpire from {ctx.author.name} expiring {newsid} in {expire} hours")
   await send_to_trol("news.expire", {'requestingUser': ctx.author.name, 'expires': expire, 'id': newsid})


@bot.command()
@onlyChannel()
@trolRol()
async def delnews(ctx):
   m = discord.utils.remove_markdown(ctx.message.clean_content).removeprefix(r"$delnews").strip()
   (m, nid) = int_maybe(m)
   (m, q) = int_maybe(m,12)
   log.debug(f"delnews from {ctx.author.name} for id {nid} to replace with expire {q} and message of '{m}'")
   if nid is None:
      await ctx.send("How about pick a number?")
      return

   await send_to_trol('news.delete', {'requestingUser': ctx.author.name, 'id': nid})
   if m is not None:
      log.debug(f"Replacing... expire {q} and message of '{m}'")
      await send_to_trol('news.add', {'requestingUser': ctx.author.name, 'message': m, 'expires': q})
   else:
      await ctx.send("Who reads this stuff anyway?")

@bot.command()
@onlyChannel()
@trolRol()
async def clearnews(ctx):
   await send_to_trol('news.clear', {'requestingUser': ctx.author.name})
   await ctx.send("There's no news like good news.")

@bot.command()
@onlyChannel()
@trolRol()
async def checknews(ctx):
   await send_to_trol('news.getdata', {'requestingUser': ctx.author.name})

@bot.command()
@onlyChannel()
@trolRol()
async def runthenews(ctx):
   await send_to_trol('news.broadcast', {'requestingUser': ctx.author.name})
   await ctx.send("Start the presses!")

@bot.command()
@onlyChannel()
@trolRol()
async def helpme(ctx):
   message =  "News Commands:\n"
   message += "   T = Number of Hours, N = News ID Number, M = News Message () = Optional\n"
   message += " $checknews         = See what news exists\n"
   message += " $addnews (T) M     = Add\n"
   message += " $newsexpire N (T)  = Change Expiration\n"
   message += " $delnews N (T) (M) = Delete (optionally re-set/edit)\n"
   message += " $clearnews         = Delete all\n"
   message += " $runthenews        = Display Scrawl NOW\n"
   message += "\n"
   message += "Other Commands:\n"
   message += " $testcamvote POS   = Start a camera change vote in position POS\n"
   message += " $camchange POS CAM = Change the camera at position POS to CAM\n"
   message += " $camcheck CAM = Show camera preview gif for CAM\n"
   message += " $helpme            = This\n"
   message += " $ping              = Pong\n"
   message += "\n"
   await ctx.send(message)

# asyncio task for websocket, then bot.run manages event loop
bot.loop.create_task(wsgo())
bot.run(conf['general']['botkey'])
