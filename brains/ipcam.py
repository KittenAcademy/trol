#!/usr/bin/python3 
#########################
# IP-based camera handling for Trol
#########################
import logging
import json

# Web
import requests
from requests.auth import HTTPDigestAuth

# Thumbs
from thread import ThreadWithLoggedException as Thread
import io
from PIL import Image
import base64
from time import time,sleep

# Config
from persist import Persist

cams = []
log  = logging.getLogger('IPCam')
log.level = logging.DEBUG

conf = None
thumbCall = None
magicCall = None

class IPCam():
   pauseUpdates = False

   def __init__(self, **kargs):
      for k,v in kargs.items():
         # log.debug(f"In IPCam() got {k}={v}")
         setattr(self,k,v)
      
      for k in ['name', 'address', 'type', 'user', 'password']:
         if not hasattr(self,k):
            raise Exception(f"IPCam requires {k}")

      self.thumbactive = False
      self.thumbthread = None
      self.thumbs = []
      if(not hasattr(self, 'capabilities')):
         self.capabilities = []
      if(not hasattr(self, 'flags')):
         self.flags = []

      self.magicactive = False
      self.magicthread = None

      self.replaceThumbnailWithDefault()
      if 'NOTHUMB' not in self.flags:
         self.startThumbThread()
      if 'MAGIC' in self.flags:
         self.startMagicThread()


   def getCapability(self, name):
      if name in self.capabilities:
         return True
      return False

   def addCapability(self, name):
      self.capabilities.append(name)

   def gotoPreset(self, preset = 1):
      raise Exception(f"Camera type has no gotoPreset()")

   def nightvision(self, setting = None):
      raise Exception(f"Camera type has no nightvision()")

   def nudge(self, x = 0, y = 0, z = 0):
      raise Exception(f"Camera type has no nudge()")

   def getRTSPURL(self):
      return self.rtspurl

   def getJPGURL(self):
      return self.jpgurl

   def getAudioURL(self):
      return self.audiourl

   def getPingURL(self):
      return self.pingurl

   def updateThumb(self, runonce = False):
      if 'NOTHUMB' in self.flags:
         log.debug(f"Thumbnails not running for {self.name} because NOTHUMB flag set.");
         return

      while self.thumbactive:
         if(IPCam.pauseUpdates == False or self.lastUpdate == 0):
            try:
               r = requests.get(self.getJPGURL(),auth=HTTPDigestAuth(self.user, self.password),timeout=conf["camTimeout"])
               sc = r.status_code
               if sc == 200:
                  self.replaceThumbnail(r.content)
                  if(thumbCall is not None):
                     thumbCall(self,self.thumbs[0][1])
                  self.lastUpdate = int(time());
               else:
                  raise Exception(f"Request for {self.name} returned {sc}")
            except Exception as e:
               # We'll just keep trying forever, but take a note.
               self.lastError = f"{e}";

         if runonce:
            return

         sleep(conf['camFetchInterval'])

      # while self.thumbactive
      log.debug(f"Inactive, dying for {self.name}")

   def replaceThumbnailWithDefault(self):
      # We expect the default thumbnail file to contain b64-encoded utf8 already
      # see replaceThumbnail
      with open(conf['defaultImage'], 'r', encoding='utf8') as f:
         self.thumbs.insert(0, [int(time()), "data:image/jpg;base64," + f.read()])
         del self.thumbs[3:]

   def replaceThumbnail(self, t):
      im = Image.open(io.BytesIO(t))
      res = im.resize([conf['thumbWidth'],conf['thumbHeight']])
      thumbIO = io.BytesIO()
      res.save(thumbIO, format='JPEG')
      b = "data:image/jpg;base64," + str(base64.b64encode(thumbIO.getvalue()), 'utf8')
      self.thumbs.insert(0, [int(time()), b])
      del self.thumbs[3:]
      # log.debug(f"Thumbset for {self.name} contains {len(self.thumbs)} items")

   def startThumbThread(self):
      self.thumbactive = True
      self.thumbthread = Thread(target=self.updateThumb, daemon=True, log=log, name=f"Camera Thumbnail Getter for {self.name}")
      self.thumbthread.start()

   def stopThumbThread(self):
      self.thumbactive = False
      if(self.thumbthread):
         self.thumbthread.join()
      self.thumbthread = None

   # Every program needs a function called doMagic because otherwise how are coders wizards?
   # TODO: Rename this
   # Right now "magic" camera refers to the system where we poll for whether a camera is online and make it live if it is, used for micro closeups from phone
   # Yes, the phone should probably push that info instead of being polled but you go to war with the code you got. -- using IP Webcam Pro on Android I can't find
   # a good way to push when we're live.
   def doMagic(self):
      purl = self.getPingURL()
      isrunning  = False
      wasrunning = False

      while True:
         if(not self.magicactive):
            log.debug(f"Magic for {self.name} dying.")
            return

         sleep(1)

         try:
            r = requests.get(purl, auth=HTTPDigestAuth(self.user, self.password),timeout=2)
            sc = r.status_code
            if sc == 200:
               isrunning = True
            else:
               isrunning = False
         except:
            isrunning = False

         if(isrunning != wasrunning):
            wasrunning = isrunning
            log.debug(f"Magic camera {self.name} state change: " + ("running" if isrunning else "inactive"))
            if(magicCall is not None):
               magicCall(self, isrunning)

   def startMagicThread(self):
      self.magicactive = True
      self.magicthread = Thread(target=self.doMagic, daemon=True, log=log, name=f"Magic for {self.name}")
      self.magicthread.start()

   def stopMagicThread(self):
      self.magicactive = False
      if(self.magicthread):
         self.magicthread.join()
      self.magicthread = None

   def addFlag(self, flag):
      if flag not in self.flags:
         self.flags.append(flag)

   def removeFlag(self, flag):
      while flag in self.flags:
         self.flags.remove(flag)


# ANPVIZ/HIKVISION see doc in resources/
class ANPVIZCam(IPCam):

   def __init__(self, **karg):
      super().__init__(**karg)
      self.addCapability('PT')
      self.addCapability('Z')
      self.addCapability('NIGHT')
      self.addCapability('PRE')

   def nudge(self, x=0,y=0,z=0):
      url = 'http://' + self.address + f'/ISAPI/PTZCtrl/channels/1/momentary'
      # momentary, xyz = speed, duration = ... duration, ms.  
      d = f'<PTZData><pan>{x}</pan><tilt>{y}</tilt><zoom>{z}</zoom><Momentary><duration>500</duration></Momentary></PTZData>'
      r = requests.put(url, auth=HTTPDigestAuth(self.user, self.password), data=d, timeout = conf['camTimeout'])
      sc = r.status_code
      if sc != 200:
         raise Exception(f"{self.name} request for nudge returned status {sc} with '{r.text}'")


   def gotoPreset(self, preset = 1):
      url = 'http://' + self.address + f'/ISAPI/PTZCtrl/channels/1/presets/{preset}/goto'
      r = requests.put(url, auth=HTTPDigestAuth(self.user, self.password), timeout = conf['camTimeout'])
      sc = r.status_code
      if sc != 200:
         raise Exception(f"{self.name} request for preset {preset} returned status {sc} with '{r.text}'")

   def nightvision(self, setting = None):
      # On ANPVIZ cameras some presets set things other than PTZ: 
      # nightvision on = preset 40
      # nightvision off = preset 39
      # nightvision auto = preset 46
      p = 46
      if setting is None:
         p = 46
      elif setting:
         p = 40
      else:
         p = 39

      return self.gotoPreset(p)

   def getRTSPURL(self):
      return 'rtsp://' + self.address + '/Streaming/Channels/101'

   def getJPGURL(self):
      return 'http://' + self.address + '/ISAPI/Streaming/channels/102/picture'

   def getAudioURL(self):
      return 'rtsp://' + self.address + '/Streaming/Channels/102'



class AMCRESTCam(IPCam):

   def __init__(self, **karg):
      super().__init__(**karg)

   def getRTSPURL(self):
      return 'rtsp://' + self.address + '/cam/realmonitor?channel=1&subtype=0'

   def getJPGURL(self):
      return 'http://' + self.address + '/cgi-bin/snapshot.cgi?1'

   def getAudioURL(self):
      return 'rtsp://' + self.address + '/cam/realmonitor?channel=2&subtype=0'



class LOREXCam(IPCam):

   def __init__(self, **karg):
      super().__init__(**karg)

   def getRTSPURL(self):
      return 'rtsp://' + self.address + '/cam/realmonitor?channel=1&subtype=0'

   def getJPGURL(self):
      return 'http://' + self.address + '/cgi-bin/snapshot.cgi?1'

   def getAudioURL(self):
      return 'rtsp://' + self.address + '/cam/realmonitor?channel=1&subtype=1'


def create_camlist(config):
   global conf, cams
   if conf is None:
      conf=config
   cdata = Persist(conf['camDefFile']).ReadData()

   # log.debug(f"Read {fn} and got {cdata}")

   ctypemap = { 'OTHER': IPCam,
                'ANPVIZ': ANPVIZCam,
                'LOREX': LOREXCam,
                'AMCREST': AMCRESTCam }
   cams = []
   for d in cdata:
      d['user']     = conf['camuser']
      d['password'] = conf['campass']
      # log.debug(f"Loading {d['name']} as type {d['type']}")
      cams.append(ctypemap[d['type']](**d));
   return cams

def get_cam_by_name(n):
   for c in cams:
      if(n == c.name):
         return c
   return None

def get_sharable_camlist(wantsthumbs=True):
   scams = []
   for c in cams:
      # TODO: Don't send private cameras/thumbs to clients who don't deserve it
      scams.append({ 'name' : c.name,
                     'flags': c.flags, 
                     'type' : c.type,
                     'thumbs': c.thumbs if wantsthumbs else [] })
   return scams

def set_thumbCall(fn):
   global thumbCall
   thumbCall = fn

def set_magicCall(fn):
   global magicCall
   magicCall = fn
 
      
if __name__ == "__main__":
   logging.basicConfig()

   tconf   = { 
      "defaultImage": "/media/raid1/stuff/Kitten Academy Resources/src/trolbrains/resources/defaultImage.b64",
      "camDefFile": "/media/raid1/stuff/Kitten Academy Resources/src/trolbrains/initialcameras.json",
      "camuser": "foo",
      "campass": "bar",
      "thumbWidth": 1920/4,
      "thumbHeight": 1080/4,
      "camTimeout": 5,
      "camFetchInterval": 5
   }


   CAMLIST = create_camlist(tconf)
   
   for c in CAMLIST:
      t = type(c).__name__
      print(f"Camera: {c.name} is of type {t}")

   #ipc = ANPVIZCam(name    = 'testcam',
   #            address = 'ka-zoom-cam4',
   #            flags   = [],
   #            user    = 'foo',
   #            password= 'bar')

   #ipc.updateThumb(runonce = True)
   #if ipc.getCapability('PT'):
   #   ipc.nudge(x=-50, y=50, z=50)
   #else:
   #   print("No nudge")

   #if ipc.getCapability('PRE'):
   #   ipc.gotoPreset(1)
   #else:
   #   print("No Presets.")

   #if ipc.getCapability('NIGHT'):
   #   ipc.nightvision(False)
   #else:
   #   print("No Night")
   print("Reached the end.")
