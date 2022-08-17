#!/usr/bin/python3
#
#  Script to store data to a JSON file and load it again after
# 
#
import os
from contextlib import contextmanager
from tempfile   import NamedTemporaryFile
from json import dump, load
from threading import Thread
from time import sleep

@contextmanager
def FaultTolerantFile(name):
    dirpath, filename = os.path.split(name)
    # use the same dir for os.rename() to work
    with NamedTemporaryFile(dir=dirpath, prefix=filename, suffix='.tmp', mode="w", delete=False) as f:
        yield f
        #f.flush()   # libc -> OS
        #os.fsync(f) # OS -> disc (note: on OSX it is not enough)
        #f.delete = False # don't delete tmp file if `replace()` fails
        f.close()
        os.rename(f.name, name)

class Persist:
   
   def __init__(self, filename="savedstate.json"):
      self.dirty = False
      self.writeback = None
      self.filename = filename

   def WriteData(self, d):
      with FaultTolerantFile(self.filename) as f:
         dump(d, f, indent=3)

   def ReadData(self):
      try:
         f = open(self.filename, mode='r')
         return load(f)
      except FileNotFoundError:
         return {}

   def isDirty(self, v = None):
      if v is not None:
         self.dirty = v
      return self.dirty

   def setWriteBack(self, func=None):
      self.writeback = func

   def runThread(self):
      self.isRunning = True
      while self.isRunning:
         if self.dirty:
            if self.writeback is not None:
               self.writeback(self)
               self.dirty = False
            else:
               raise Exception("We are dirty and we are threaded but we have no writeback!")

         sleep(1)

   def stopThread(self):
      self.isRunning = False

if __name__ == "__main__":
   data = { "key1": "Valuething", "key2": 3 }
   #"This is a test data."
   p = Persist(filename="test.json")

   rd = p.ReadData()
   print(f"Read at start: {rd}")

   p.WriteData(data)
   rd = p.ReadData()
   print(f"Written: {data}\nRead: {rd}")

   def wb(pobj):
      d = { "key1": "InCallback" }
      print(f"In callback, writing: {d}")
      p.WriteData(d)

   p.setWriteBack(wb)

   t = Thread(target = p.runThread)
   t.start()
   assert p.isDirty() == False
   assert p.isDirty(True) == True
   while(p.isDirty()):
      print("Waiting for thread to clear")
      sleep(1)

   p.stopThread()
   print("Waiting for thread to end.");
   t.join()

   rd = p.ReadData()
   print(f"Read after thread: {rd}")




