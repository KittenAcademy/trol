# trol 

trol, originally called KA-Control until part of the signage was stolen for another purpose.  

trol is a system for controlling the live broadcast at Kitten Academy, but should (eventually) be useful for anyone running a similar
stream -- similar meaning a large number of RTSP-based IP webcams that need to be switched and positioned in real-time for a livestream/broadcast

trol currently consists of four major components:

## brains -- brains/tb2.py

This is the heart of the system and responsible for coordinating all the parts, which it does by running a websocket server which the other parts
connect to as clients.  Major functionality (aside from all the websockety stuff) includes the logic and persistent data for all the cameras, polling 
and generating thumbnails constantly for clients consumption, and managing the news scroll data and logic as well.  

The brains configuration files are the source for all the information about all the cameras.

## xsplit 
### xsplit/ka-control2.html

This is the xsplit extension that handles the majority of the communication between xsplit and trol.  We try to keep xsplit as "dumb" as possible, and keep
as much of the logic abstracted out, in other parts of the overall system, so this plugin is primarily responsible for:

1. On startup, reads the xsplit presentation data, compiles a list of every scene and within those scenes, any RTSP source items that are named beginning with "TROL ".  That data is sent to trol.
2. Whenever trol sends a message telling it to, it will replace the URL in one of the "TROL "-named RTSP sources with a URL specified by trol.

### xsplit/trolscrol.js

Because of how xsplit is architected, this is a separate script that needs to be loaded into a text control to actually update the news scroll text.

## jsclient -- jsclient/client.html

This is a javascript client to trol, intended to allow complete control over the broadcast -- eventually.  At the time of initial release,
it's able to display and select from all the cameras and positions available.

We only test this inside an Android webview (code not yet reviewed/published) and the most recent version of Firefox.  Any other js consumer, YMMV.

## bot -- bot/trolbot.py

This is a Discord bot that currently allows a limited set of Kitten Academy discord users to control the camera selection and the news scroll.  The intent is to try some 
form of crowd-sourced vote-based camera selection at times when the people ultimately responsible aren't paying attention.  And other fun things.

# Setup

Uh, good luck.

**VERY IMPORTANT NOTE** 

One important note throughout, as of this writing, trol will check all incoming connections from all clients and expects them all to be from a private, unroutable IP
range e.g. 192.168.0.1/24 (that's not a guarantee, off the top of my head, if you have a secure cert set up in the config then it will allow from external but that's
not been tested on this release and may break all kinds of things) (related: don't set up a secure cert, trol will not use it for connections from unroutable IP ranges
even if you do) (related: trol only supports ipv4)

## Brains:

Check out the brains/sampleconf files - edit them to suit your deployment, start up a trolbrains systemd service and check the logs.

## Xsplit Broadcaster:

### Config File

Check out xsplit/config.js.sample and copy/rename it to config.js in the same directory

### Presentation

A minimum viable presentation will contain a scene, the scene will contain a source of the type you get when you "Add Source" -> "Streams" -> "IP camera (RTSP)"

That source, or any number of them, need(s) to be given custom name(s) (double-click the item in the scene list) in the form "TROL NAME" where NAME 
is the camera "Position" in trol.  

example: the Top Right camera position at KA is named "TROL TR" and we refer to it as "TR" everywhere as a result.  

**THE NAME OF THE SOURCE IN XSPLIT IS WHERE trol LEARNS ABOUT THE AVAILABLE POSITIONS -- THIS IS WHERE THEY ARE CREATED, and anything named "TROL "-whatever is considered a position.**

Special note: Sources named "TROL A"-whatever are treated as audio-only sources.  This will certainly change, but for now... example: At Kitten Academy we have sources named
"TROL A1" and "TROL A2" that are normal RTSP sources like the rest, but positioned behind the rest, so not visible on stream.  They are the ONLY sources with the audio unmuted.  All 
the rest of the sources, we muted the audio.  This way, only cameras placed in these two positions can be heard, allowing trol a way to control the audio selection separately 
from the video selection.  (And yes, as this implies, if you want camera "X" to be seen and heard, you'll need to put it in two positions, one named "TROL A"-something and one named
"TROL "-something-that-doesn't-begin-with-A

If you make any source that is named "TROL "-whatever that is not an RTSP source, things will end badly for you.  But you can have as many as you like with other names.
e.g. at Kitten Academy the black borders are a "image" source named "Borders" and that's fine, but an image source named "TROL Borders" would be a disaster tantamount to 
crossing the streams.

Or you can ask Kitten Academy for a copy of the presentation they use, which we'll publish "in due time." (Xsplit presentation files seem leaky so Mr. A needs to make a 
fresh one for publishing)

Finally, of course, you must add the plugin: Extensions -> Add Extension, find the ka-control2.html file and click it.

As soon as you start the xsplit extension, if all is working, it should immediately connect to the trolbrains websocket and there will be something to indicate it in
the trolbrains log.  If you need the xsplit log, its position varies but can be found by choosing tools -> settings -> advanced, then hover your mouse over the '?' icon 
near the words "Enable enhanced logging" and in the tooltip, in the basement, in a disused lavatory behind a sign saying "beware of the leopard" you will find a link to
the Xsplit log.

### News Scroll - OPTIONAL

Add a source, "Add Source" -> "Text..." and in the text source, choose "Script", "Custom script" and paste the contents of xsplit/trolscrol.js in there.  Optionally set the 
source under Styles -> Animation, Scroll, etc. You should see it connecting to the brains websocket immediately.

## Discord Bot - OPTIONAL

See the discord.conf.example and trolbot.service files in the bot directory.  You'll need to create your own 'app' for the credentials -- do this in the Discord
developer portal.  It's confusing as heck if you've never been through the process.

1. https://discord.com/developers/applications
2. ...good luck!

## JavaScript/Web Client - OPTIONAL

"Optional" but c'mon you need to use trol somehow, it's nothing just sitting on its own.

We just serve the entire contents of the jsclient directory on our internal http server and load up client.html in a web browser.  We also have a android app that's 
literally just a WebView set to load the same html from our internal server.  

The js client expects to find images named scn\_NAME.png for each scene you have defined in xsplit, where NAME matches the xsplit name, of course.

Quick how-to use the js client: 

When it connects you'll see the positions (anything named "TROL "-whatever in xsplit) at the top, then all the cameras (defined in 
brains/sampleconf/initialcameras.json) and finally the scenes in xsplit at the bottom.  Currently broadcasting cameras have a green border.  

To switch a camera at a position, click the position (should be highlighted), then click the camera.  

If you click a camera once, it's selected, then you can click a position to set it there.  Or, click a camera twice, different highlight, now you can select mulitple
cameras with clicks and then click a position to set all the cameras in rotation there.  

If you click a scene, you should see a message telling you how many more times to click it to make it active -- this is to prevent "butt broadcasting"

# Big Goals/TODO

1. Replace the entire xsplit portion with something nice and something open.  Probably OBS or even, for our needs, a few scripts around ffmpeg/libav... of course, that's how you get yet another OBS/Xsplit so best to avoid that mess.  So yes, OBS most likely but not a foregone conslusion.  But it must be open.

2. Lots of code cleanup, consistency, refactoring, rearchitecting -- this has all been done while I'm simultaneously learning JavaScript, Python, and way too much about Xsplit Broadcaster, all while having no clear architecture in mind... so it's a sloppy mess.



