# Original Author: Johan Hanssen Seferidis
# License: MIT
# See the end of this file.

import threading

class ThreadWithLoggedException(threading.Thread):
   def __init__(self, *args, **kwargs):
      if "log" in kwargs:
         self.log = kwargs.pop("log")
      else:
         raise Exception("Missing 'log' in kwargs")

      super().__init__(*args, **kwargs)
      self.exception = None

   def run(self):
      try:
         if self._target is not None:
            self._target(*self._args, **self._kwargs)
      except Exception as exception:
         thread = threading.current_thread()
         self.exception = exception
         self.logger.exception(f"[ EXCEPTION IN THREAD {thread} ]\n{exception}\n[ THIS SPACE INTENTIONALLY LEFT BLANK ]")
      finally:
         del self._target, self._args, self._kwargs

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
