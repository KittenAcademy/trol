#!/usr/bin/python3 -u
import os
import pathlib
import pipelineforlosers as p
import subprocess

print("justmove.service starting...")


p.fileUnchangedTime = 60
# Only files with this extension will be considered:
p.fileext = '.mp4'
# Where to watch for files to appear
p.watchdir = '/mnt/incoming'
# Where to move a file after upload
p.movedir  = '/mnt/outgoing'


def cb(fn):
   print(f"Moving file {fn} to {p.movedir}")
   # We don't actually do anything here, the pipeline lib defaults to moving the files after invocation
   return True

def postmove(fn):
   print(f"Informing trol of {fn}")
   subprocess.run(["python3", "./trolcli.py", "--wsurl", "ws://troltest_brains:8081", fn])
   # We don't actually do anything here, the pipeline lib defaults to moving the files after invocation
   return True

p.addExisting()
p.call_me_maybe(cb,postmove)

print("We're done here.") 

