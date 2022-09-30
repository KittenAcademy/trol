#!/usr/bin/python3
##################
# Manages news items for Trol - should be called scroll or something rather than news really.
#
# Poor design copied from v1
##################
from time import time 

DEFAULT_TIME = 12  
# Time in hours for new messages to be on stream
INTRO = "" 
OUTRO = "   "
MESSAGESEP = " [img]https://chris-jansen.squarespace.com/s/supertiny-white-transparent.png[/img] "

class News():

   def __init__(self, initial_items=[]):
      print(f"Setting initial items to {initial_items}")
      self.items = initial_items

   def idExists(self, id):
      for i in self.items:
         if i['id'] == int(id):
            return True
      return False

   def getNextID(self):
      nid = 0
      while True:
         nid += 1
         if not self.idExists(nid):
           return nid
         if nid > 100:
            raise Exception("Too many news items!")

   def addItem(self, message, t = DEFAULT_TIME): 
      t = time() + (60 * 60 * t)
      self.items.append({'message': message, 'expires': t, 'id': self.getNextID()})

   def getItems(self):
      self.expireItems()
      return self.items

   def changeExpire(self, id, t = DEFAULT_TIME):
      for i in self.items:
         if i['id'] == int(id):
            i['expires'] = time() + (60 * 60 * t)

   def delItem(self, id):
      for i in self.items:
         if i['id'] == int(id):
            i = None
      self.items = [i for i in self.items if i is not None] # And I thought Python was supposed to be smart

   def expireItems(self):
      now = time()
      for i in self.items:
         if i['expires'] < now:
            i = None
      self.items = [i for i in self.items if i is not None] # And I thought Python was supposed to be smart

   def getScroll(self):
      self.expireItems()

      if(len(self.items) == 0):
         return "";

      news = INTRO
      for i in self.items:
         news += i['message'] + MESSAGESEP
      news += OUTRO 
      return news
      
