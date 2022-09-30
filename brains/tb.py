#!/usr/bin/python3
#############################
# Trol "Brains" v2
#
# This is the "heart" of the "Brains"
#
# Everything interesting we do here is via callbacks from wsserver which handles the network communication websocket.
import argparse
import logging

# Threading
from threading import enumerate as enumThreads
from thread import ThreadWithLoggedException as Thread

# Websocket Server
from tserv import create_server, register_message, start_server, close_server

# Cameras
import ipcam

# Scrawl? Scrull?
from news import News

# config file is json
import json

# reads/writes json formatted data intended for easy persistent data between
# executions
from persist import Persist

from sys import exit
from time import time,sleep
from datetime import datetime

# Set up logging
logging.basicConfig()
log = logging.getLogger('trol')
log.level = logging.DEBUG

# Get config
conf = {}
try:
   aparse = argparse.ArgumentParser()
   aparse.add_argument('-c', '--config', help='json formatted config file', default='conf/wsconf.json')
   aparse.add_argument('-p', '--port', help='override configured port')
   args = aparse.parse_args()
   conf = json.load(open(args.config))
except:
   log.critical("Cannot loaf config.")  # Mmm, config loaf
   aparse.print_usage()
   exit()

if(args.port):
   conf['WSPORT'] = int(args.port)


# Who wants 'em
thumbusers = []
camusers   = []

# Should be called scroll rather than news, but OK
newsusers  = []
news = None
try:
   news = News(Persist(conf['newsfile']).ReadData().get('NewsItems', []))
except Exception as e:
   log.debug("Exception reading old news file: {e}")
   news = News()

# Data from xsplit on which scenes and positions are available
scenedata       = []
activescene     = None
activepositions = Persist(conf['posfile']).ReadData()
activerotations = {}
poslastchange   = {} 

###
### s = global websocket wsserver object
###
s = create_server(port=conf['WSPORT'],host=conf['WSHOST'],key=conf['WSKEY'],cert=conf['WSKEY'],loglevel=logging.DEBUG, clientTimeout=300)
# Note: clientTimeout here is how long we sit in a readloop or writeloop waiting for data before we quit.  It is NOT the timeout set on the socket, which is 
# shorter than this (we hope) and it's not the timeout that's likely to get a client disconnected, see the end of this file for the more likely timeout - we disconnect
# clients that don't respond to a ping once a loop in our main loop below.

###
### cams = global camlist 
###
cams = ipcam.create_camlist(conf)

###
### Callback functions for trol messages
###

# user.hello: user=set user name
def UserHello(c,m):
   """Process a user.hello message:

   This message allows a user to specify who/what they are e.g "xsplit" or "Mr. A."
   Currently the only authorization is based on whether they are coming from *inside the house*.
   This message also lets the client indicate interest in receiving certain kinds of updates; 
   thumbnails, camera data, news -- why do we keep each of these as a list of users rather than
   just checking the presence of the flag(s) in the master list?  Good question.
   """
   if('user' not in m):
      log.warning(f"User {c.id} sent badly formed user.hello: {m}")
   elif(c.user == 'HOUSE'):
      c.user = m['user']
      log.debug(f"User {c.id} sent user.hello, name changed to {m['user']}")
   else:
      log.warning(f"User {c.id} sent user.hello but we didn't understand {m}")

   wantsthumbs=False
   if('thumbs' in m and m['thumbs']):
      wantsthumbs=True
      thumbusers.append(c)

   # TODO: These need to be finer-grained, not all clients need all this junk
   if('cams' in m and m['cams']):
      camusers.append(c)
      # New client welcome package: 
      # 1 - list of cameras 
      # TODO: differentiate public/private clients
      # Kind of done, right now we send all cameras to the clients and all clients are trusted but once we 
      # have untrusted clients, which is the plan, we'll need TODO better.  See trolbot for an example of 
      # only sharing public cameras
      c.send_message("server.camlist", { "cams": ipcam.get_sharable_camlist(wantsthumbs) })
      if(len(scenedata) > 0): # We learn this from a client so we may not know it yet.
         # 2 - list of scenes and the positions they contain
         c.send_message("xsplit.scenedata", { "scenedata": scenedata })
      if(activescene is not None): # We learn this from a client so we may not know it yet.
         informScenechanged([c]) # Also will inform positional data 

   if('news' in m and m['news']):
      newsusers.append(c)
      c.send_message("news.setscrolldata", { "scrolldata": news.getScroll(), "newsdata": news.getItems() })

   # If the new user is xsplit, send them all the positions as fresh so that what we think is true... is true
   # otherwise they could have something on that we don't expect.
   if user_is_xsplit(c):
      for p in activepositions:
         DoPositionChange(p, activepositions[p])
register_message("user.hello", UserHello)

# xsplit.scenedata: scenedata={scenename: [position, position, position], ...}
def XsplitScenedata(c,m):
   """Process an xsplit.scenedata message

   The xsplit.scenedata message comes from xsplit and contains a mapping of scene names that 
   xsplit knows about to positions that scene contains.  This is our only authoritative reference
   for what scenes and positions exist.
   """
   global scenedata
   # TODO: We replace the scenedata wholesale but we maintain the position data below -- maybe we should think more
   # about whether one or the other works for both.
   scenedata = m['scenedata']
   # Make sure only xsplit can send this message to us
   if(not user_is_xsplit(c)):
      log.warn(f"Got scenedata from non-authorized user: {c.id}({c.user})")
      return
   for s in scenedata:
      for p in s['positions']:
         if(not (p in activepositions and activepositions[p])):
            activepositions[p] = "null" # If this is a position that's new to us and not already set, default it to set null.
            log.debug(f"We learned a new position: {p} in scene {s['name']}")
   send_to_list(camusers, "xsplit.scenedata", m, but=c)
register_message("xsplit.scenedata", XsplitScenedata)

# xsplit.scenechanged: scene=name, name=name, oopsall=names
def XsplitScenechanged(c,m):
   """Process xsplit.scenechanged message

   The xsplit.scenechanged message comes from xsplit to inform us when a scene has been made live.  It's typically
   a result of a request.scenechange message sent to xsplit.
   """
   global activescene 
   if('scene' in m):
      activescene = m['scene']
   elif('name' in m):
      activescene = m['name']
   else:
      log.warning("Got scene changed info not including scene name?")

   log.debug(f"Set the scene: {activescene}")
   informScenechanged()
register_message("xsplit.scenechanged", XsplitScenechanged)

def informPositions(clist=camusers):
   """Send data about active positions/rotations to a list of clients"""
   for p in get_scene_by_name(activescene)['positions']:
      send_to_list(clist, "xsplit.positionchanged", { "pos": p, "cam": activepositions[p] });
   # 5 - send rotation data as part of position data
   send_to_list(clist, "server.activerotations", { "activerotations": activerotations });

def informScenechanged(clist=camusers):
   """Send data about active scene to a list of clients"""
   send_to_list(clist, "xsplit.scenechanged", { "scene": activescene, "name": activescene})
   informPositions(clist)

# request.scenechange: scene=name
def RequestScenechange(c,m):
   """Process a request.scenechange message from a client

   All we need to do here is forward it on to xsplit really."""
   to = ''
   if('scene' in m):
      to = m['scene']
   elif('name' in m):
      to = m['name']
   else:
      log.warning(f"{c.id} requested scene change without scene")
      return

   for s in scenedata:
      # Verify requested scene exists
      if(to == s['name']):
         send_to_xsplit("request.scenechange", { "scene": to, "name": to })
         return

   log.warning(f"{c.id} requested scene change to unknown scene {to}")
   return
register_message("request.scenechange", RequestScenechange)


def endRotation(pos):
   """Stop a camera rotation in position pos"""
   if(pos in activerotations):
      del activerotations[pos]
      informPositions() # should be just informRotations maybe?

# request.positionchange: pos=posname, cam=camname, url=
def RequestPositionchange(c,m):
   """Process a request.positionchange message from a client

   Again, all we need to do here is basically validate it and forward to
   xsplit
   """
   if('pos' not in m):
      log.warning(f"{c.id} requested position change without position.");
      return;
   if('cam' not in m):
      log.warning(f"{c.id} requested position change without cam.");
      return;
   # TODO: Validate, auth, etc.

   # First rule of position change: If a local user (in the house) has changed the position within the last minute,
   # don't allow changes through the bot.  
   if poslastchange.get(m['pos']) and user_is_bot(c):
      if time() - poslastchange[m['pos']] < 60:
         log.warning(f"{c.id} requested position change for {m['pos']} but denied due to time limits")
         c.send_message('user.error', { "errmsg": f"{m['pos']} changed by Mr. A or DJ, wait a minute." })
         return
   # Second rule of position change: If we have a "MAGIC" camera in that position, bot users can't touch it.
   if "MAGIC" in ipcam.get_cam_by_name(activepositions[m['pos']]).flags and user_is_bot(c):
      log.warning(f"{c.id} requested position change but MAGIC in position {m['pos']}")
      c.send_message('user.error', {  "errmsg": f"{m['pos']} showing close-up." })
      return

   # If we have a rotation happening but got a request to change the camera from 
   # elsewhere then that means we're done rotating.
   endRotation(m['pos'])

   DoPositionChange(m['pos'], m['cam'])
   # Log time of last positionchange request from local users for lockout/rate limiting
   # TODO: c'mon what is this mess?  
   if not user_is_bot(c):
      poslastchange[m['pos']] = int(time())

register_message("request.positionchange", RequestPositionchange)

def DoPositionChange(pos,cam):
   """Send a request.positionchange message to xsplit

   Called when a client sends us a request.positionchange or when we need to send our own,
   such as for camera rotation or magic camera.
   """
   url   = ipcam.get_cam_by_name(cam).getRTSPURL()
   if(pos.startswith('A')):
      url   = ipcam.get_cam_by_name(cam).getAudioURL()

   # Send only to xsplit, because of the 'url' being possibly sensitive data
   send_to_xsplit("request.positionchange", { "pos": pos, "cam": cam, "url": url })

# xsplit.positionchanged: pos=posname, cam=camname
def XsplitPositionchanged(c,m):
   """Process an xsplit.positionchanged message

   Obviously now, this is what we get from xsplit when a camera has been put live
   in a position, typically caused by having sent xsplit a request.positionchange
   """
   if('pos' not in m):
      log.warning(f"{c.id} notified position change without position.")
      return
   if('cam' not in m):
      log.warning(f"{c.id} notified position change without cam.")
      return

   tocam = m['cam']
   topos = m['pos']
   activepositions[topos] = tocam
   send_to_list(camusers, "xsplit.positionchanged", { "pos": topos, "cam": tocam }, but=c)
register_message("xsplit.positionchanged", XsplitPositionchanged)

# This is us, switching cameras automatically every X seconds.
# request.rotation: pos=posname, cams=[camname,camname,...] 
def RequestRotation(c,m):
   """Start a camera rotation, switching between cameras in a position every X seconds."""
   global activerotations
   if('pos' not in m):
      log.warning(f"{c.id} requested rotation without position.")
      return
   if('cams' not in m):
      log.warning(f"{c.id} requested rotation of no cameras.")
      return

   rotInterval = m.get('interval', conf['camRotationInterval'])

   topos = m['pos']
   # TODO: validate cameras, auth
   if(topos in activerotations):
      activerotations[topos] = m['cams']
      return

   activerotations[topos] = m['cams']
   Thread(target=rotThread, args=(topos,rotInterval,), daemon=True, log=log, name=f"rot-{topos}").start()
   informPositions() # TODO: Should be informRotations maybe?
register_message("request.rotation", RequestRotation)

def rotThread(pos, interval):
   """Every X seconds, switch the camera in the given position to the next one in a list."""
   global activerotations
   while True:
      if(pos not in activerotations):
         log.debug(f"{pos} rotation handler dying, no entry")
         return
      if(len(activerotations[pos]) == 0):
         log.debug(f"{pos} rotation handler dying, no cams")
         return
      # Take the camera from the front of the list, activate it, and return it to the back
      acam = activerotations[pos].pop(0)
      activerotations[pos].append(acam)
      DoPositionChange(pos, acam)
      log.debug(f"{pos} rotation handler set cam: {acam} see you in {interval}...")
      sleep(interval)

# camera.thumb: name = camera data=b64 encoded thumbnail
def thumbCallback(cam, data):
   """Receive a fresh camera thumbnail image and send it to anyone who wants thumbnails."""
   send_to_list(thumbusers, "camera.thumb", { "name": cam.name, "data": data })
ipcam.set_thumbCall(thumbCallback)



def DoRecording(start = True):
   """Start or stop a recording on xsplit"""
   # TODO: Signal your intentions with more intention
   # TODO: Send this only where it needs to go
   # Send to everyone because xsplit needs it and trolbot uses it to know when magiccam is likely on
   s.send_message_to_all("request.recording", { "record": start })


def magicCallback(cam, isactive):
   """Start or stop a "magicCam"(aka micro closeup) - automatic camera selected to display (and record) when online"""
   global lastcam
   log.debug(f"Got magic callback for {cam.name} {isactive}")
   # TODO: Lazy, hardcoded position, but not just here, also in the script that compiles the micros for upload
   pos = "TR"
   if(isactive):
      lastcam = activepositions[pos] or "null"
      if(lastcam == cam.name):
         log.warning(f"{cam.name} already on?")
      # TODO: Preserve an active camera rotation and return to it afterwards instead of just killing it and 
      # returning to whatever camera happened to be active
      endRotation(pos)
      DoRecording(True)
      DoPositionChange(pos, cam.name)
   else:
      if(lastcam == cam.name):
         log.warning(f"{cam.name} wants to be {lastcam} how?")
      if(lastcam == "null"):
         log.warning(f"{cam.name} wants to be null why?")
      DoPositionChange(pos, lastcam)
      DoRecording(False)
ipcam.set_magicCall(magicCallback)

def send_to_list(who, mt, mess={}, but=None):
   """Send a message to a given list of users, optionally excluding one member of the list

   This should be a member function in the wsserver, why is it here?
   """
   for c in who:
      if(but == c):
         continue
      c.send_message(mt, mess)

# TODO: Start validating who the bot is passing requests on behalf of, rather than
# just giving the bot itself permissions to do/not do.  Or in addition to I suppose.
def user_is_bot(c):
   """Check if a user is trolbot"""
   # TODO: Get in proper users and permissions oh I said this already.
   if(c.islocal and "trolbot" in c.user):
      return True
   return False

def user_is_xsplit(c):
   """Check if a user is xsplit"""
   # TODO: Get in proper users and permissions
   if(c.islocal and "xsplit" in c.user):
      return True
   return False

def send_to_xsplit(mt, mess={}):
   """Send a message but only to users who are xsplit"""
   for c in s.clients:
      if(user_is_xsplit(c)):
         c.send_message(mt, mess)

def user_left(c,serv):
   """Remove all references to a user because they disconnected."""
   while(c in thumbusers):
      thumbusers.remove(c)
   while(c in camusers):
      camusers.remove(c)
   while(c in newsusers):
      newsusers.remove(c)
s.set_callback("client_disconnected", user_left)

def get_scene_by_name(n):
   """Just what the function name says"""
   global scenedata
   for s in scenedata:
      if(s['name'] == n):
         return s;
   # raise Exception(f"Got request for scene {n} that doesn't exist.")
   # Exception commented out because we expect to not know any scenes when we first boot
   # xsplit has to tell us about them after they are connected but this will get called
   # before then.

def newsThread():
   """Wake up every "newsInterval" seconds (in config) to ask xsplit to display the news scroll"""
   def setNextNews():
      """Return the next time that's a multiple of newsInterval past the hour

      We use this method so that if the newsInterval is (for example) 15 minutes, then we will display the news
      precisely at 00, 15, 30, 45 minutes past, instead of every 15 minutes from a random start e.g. 3,18,33,48 
      which would be weird.
      """
      nt = datetime.now().replace(minute=0,second=0).timestamp()
      while(nt <= time()):
         nt += conf['newsInterval']
      return nt;

   nextTime = setNextNews();

   while True:
      if(nextTime < time()):
         try:
            if(len(news.getItems()) == 0):
               send_to_list(newsusers, "news.setscrolldata", { "scrolldata": news.getScroll(), "newsdata": news.getItems() })
               log.debug("No gnus is good gnus.")
            else:
               log.debug("Start the presses!")
               send_to_list(newsusers, "news.showscrolldata", { "scrolldata": news.getScroll(), "newsdata": news.getItems() })
         except Exception as e:
            log.warning(f"Exception Running the News: {e}")

         nextTime = setNextNews()
      log.debug("We'll check back in " + str(int(nextTime - time())))
      sleep(nextTime - time())
Thread(target=newsThread, daemon=True, log=log, name=f"newsThread").start()

def doNewsStuff(c,m):
   """Handle all news-related messages

   Kind of suggests that the callback frunction should have an option to say something like news.* to tell it to just
   call this function for every news. prefixed mtype...but it doesn't, yet.
   """
   global news
   datachanged = True
   mtype = m.get("mtype")
   # Python added a switch (they call 'match') but we don't have it in our old Debian version of Python.
   if(mtype == 'news.clear'): # Delete all news
      news = News()
   elif(mtype == 'news.getdata'): # return news in "internal" format (i.e. w/ metadata)
      c.send_message('news.data', { "newsdata": news.getItems()})
      datachanged = False
   elif(mtype == 'news.broadcast'): # Ask xsplit to actually display the news (how long to display decided in xsplit code)
      if(len(news.getItems()) == 0):
         log.info(f"{c.id} asked for news broadcast, but there's no news.")
         return
      send_to_list(newsusers, "news.showscrolldata", { "scrolldata": news.getScroll(), "newsdata": news.getItems() })
      datachanged = False
   elif(mtype == 'news.add'): # Add a new news item
      news.addItem(m.get('message'), m.get('expires'));
   elif(mtype == 'news.expire'): # Change a news item expiration date
      news.changeExpire(m.get('id'), m.get('expires'));
   elif(mtype == 'news.delete'): # Delete a news item
      news.delItem(m.get('id'))

   if datachanged:
      send_to_list(newsusers, "news.setscrolldata", { "scrolldata": news.getScroll(), "newsdata": news.getItems() })
   log.debug(f"Handled {mtype}")
register_message("news.clear", doNewsStuff)
register_message("news.getdata", doNewsStuff)
register_message("news.broadcast", doNewsStuff)
register_message("news.add", doNewsStuff)
register_message("news.expire", doNewsStuff)
register_message("news.delete", doNewsStuff)

def doNothing(c,m):
   """Just like the function name says - used to surpress "unhandled mtype" warnings"""
   pass
register_message("user.pong", doNothing)


####################################
### Main thread loop
####################################
start_server()
maincycletime = 120
while True:
   sleep(maincycletime)
   timenow = time()
   #for t in enumThreads():
   #   log.debug(f"Active Thread: {t.name}")

   # If we don't hear anything from a client for one cycle, prod them with a ping - if two cycles, kill them.
   for c in s.clients:
      if(timenow - c.lastactivetime > (maincycletime * 2)):
         log.warning(f"Active Client: {c.id}({c.user}) Inactive for > 2 cycles.  Killing...")
         c.keep_alive = False
      elif(timenow - c.lastactivetime > maincycletime):
         log.debug(f"Active Client: {c.id}({c.user}) Inactive for 1 cycle.  Pinging...")
         c.send_message("server.ping", { "time": time() })
      else:
         log.debug(f"Active Client: {c.id}({c.user})")

   # TODO: Put this functionality someplace less arbitrary
   # Write important state data to files so if we are killed we don't forget everything.
   # 
   Persist(conf['posfile']).WriteData(activepositions)
   Persist(conf['newsfile']).WriteData({ 'NewsItems': news.getItems() })

# We'll get to this in due time
close_server()
