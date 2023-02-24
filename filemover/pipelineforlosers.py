#!/usr/bin/python3 

#   1. Watch directory for files, when one appears spawn a thread to watch it
#   2. Watch files, if they have not changed size in X seconds then
#   3. Add their names to queue
#   4. Main thread pulls names from queue and calls the callback for each one

# Version to account for the fact that windows samba shares don't do inotify events.


import os
import threading
import pathlib
import time
import queue
# pathlib.rename is fucked when you have different file systems. 
from shutil import move


# Only files with this extension will be considered:
fileext = '.mp4'
# Where to watch for files to appear
watchdir = './watch'
# Where to move a file after upload
movedir  = './done'
# how long in seconds a file must be unchanged before callback
fileUnchangedTime = 30
# If a file with this name exists in watchdir, stop running.
stopfile = 'STOP.STOP'



# Queue of filenames that are ready to upload
class SetQueue(queue.Queue):
   def _init(self, maxsize):
      self.queue = set()
   def _put(self, item):
      self.queue.add(item)
   def _get(self):
      return self.queue.pop()

filequeue = SetQueue()

# Exception that indicates we need to try again later (tomorrow - quota)
class TryAgainLater(Exception):
   pass


def call_me_maybe(callback, postcallback=None):

   def watch_for_files(pathname=watchdir, cycle_time=fileUnchangedTime):
      try:
         p = pathlib.Path(pathname)
         files = {}
         print(f"Beginning filewatch on directory: {p.as_posix()}")
         while True:
            for fn in p.glob("*"+fileext):
               filesize = pathlib.Path(fn).stat().st_size
               if(fn in files):
                  if(files[fn] != filesize):
                     print(f"File {fn} {filesize} still growing")
                     files[fn] = filesize
                  else:
                     print(f"File {fn} {filesize} done!")
                     filequeue.put(fn)
               else:
                  print(f"New file: {fn} {filesize}");
                  files[fn] = filesize;

            #print(f"Done, sleeping for {cycle_time}")
            time.sleep(cycle_time)
      except Exception as e:
         print(f"Exception: {e} in watcher thread")
         return

   threading.Thread(target=watch_for_files, daemon=True).start();

   while True:
      sf = pathlib.Path(f"{watchdir}/{stopfile}")
      if sf.exists():
         print(f"Stopping because of stopfile {sf}")
         break

      filename = filequeue.get() # queue docs say this blocks forever on some shitty OSes 
      # like ours maybe when it's empty?  Something's not wokring.
      if(not pathlib.Path(filename).exists()):
         print(f"File no longer exists, aborted callback: {filename}")
         next

      print(f"Calling you back to handle {filename}")

      automove = True
      while True:
         try:
            if callback(filename) == False:
               automove = False
               print(f"Callback returned false; don't move files.")
            break
         except TryAgainLater:
            print(f"Callback asked us to try again in an hour.")
            time.sleep(3600)
      

      pf = pathlib.Path(filename)

      if(not pf.exists()):
         print(f"File no longer exists, aborted move: {filename}")
         next

      destname = movedir + '/' + pf.name
      if pathlib.Path(destname).exists():
         raise Exception(f"Error: destination exists: {destname}")

      move(pf, destname)
#     pf.rename(destname) # doesn't work across filesystems.
      print(f"Moved finished upload to: {destname}")
      if postcallback is not None:
         print(f"Calling you back to handle {destname}")
         postcallback(destname)

def addExisting():
   pass
   # in this shitty version we do nothing here.

if __name__ == "__main__":
   def cb(fn):
      print(f"I'm stupid, I don't do any work and I just complain about {fn}")

   addExisting()

   call_me_maybe(cb)


