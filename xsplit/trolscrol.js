/*
 * Script loaded within the text source in Xsplit, all it does it listen for updates from trol and change its own text
 * because to users of xjs, this makes more sense than being able to set the contents of a source directly from your extension/plugin
 *
 */
let WSURL = "ws://superswarm:8081/"
// State used by sockReconnect() below
let sock = createSock();
let sockFails = 0;
let sockTimer = null;

async function sockHandleMessage(event)
{
	// console.log("Got from server: " + event.data);
   let d = {}
   let scrolltext = ""
   try {
      d = JSON.parse(event.data);
      scrolltext = d.scrolldata;
   } 
   catch(e) {
      console.log("Can't parse as JSON.");
      // Data isn't JSON, just ignore.
      return;
   }

   if(d.mtype == 'news.setscrolldata')
   {
      console.log("Set scroll to ###" + scrolltext + "###")
      SetText(scrolltext);
   }
   if(d.mtype == 'news.showscrolldata')
   {
      console.log("Set scroll to ###" + scrolltext + "###")
      SetText(scrolltext);
   }
   if(d.mtype == 'server.ping')
   {
   	sock.send(JSON.stringify({mtype: "user.pong", time: 'whatev'}));
   }

}

// Reconnect to WebSocket Server - we can't do anything without it!
function sockReconnect()
{
   if(sockFails != 0)
   {
      console.log("Request to reconnect but we're already trying with " + sockFails + " fails.");
      return;
   }

   if(sockTimer != null)
   {
      console.log("Request to reconnect but we're already trying with an active Timer.");
      return;
   }

   if(sock.readyState != 3) // 3 == CLOSED
   {
      console.log("Request to reconnect but socket state is " + sock.readyState);
      return;
   }

   function _sr() 
   {
      // Magic number 1 means we're connected.
      if(sock.readyState == 1)
         return;

      // readyState == 0 if we are currently connecting
      // so let that carry on and check back
      if(sock.readyState != 0) 
      {
         sock = createSock();

      }

      // multiplicative backoff tops out at 5 seconds
      sockFails++;
      let mult = (sockFails > 5) ? 5 : sockFails;
      sockTimer = setTimeout(_sr, delay = 1000 * mult);
   }

   _sr();
   
}

function createSock() 
{
   s = new WebSocket(WSURL);
   s.addEventListener('close', sockHandleClose);
   s.addEventListener('open', sockHandleOpen); 
   s.addEventListener('message', sockHandleMessage);
   return s;
}

// The close event is emitted if we fail to connect in the first place too
function sockHandleClose(ev)
{
	console.log("Server disconnect.");
   sockReconnect();
}

async function sockHandleOpen(ev)
{
   // Since we just got a good connection let's reset any connection attempts in progress
   stopReconnect();
	sock.send(JSON.stringify({mtype: "user.hello", user: 'scroll', "news": true}));
}

function stopReconnect()
{
   if(sock.readyState != 1) // Magic number 1 means connected
      console.log("Stopping connecting even though socket state is " + sock.readyState);

   sockFails = 0;
   // "Passing an invalid ID to clearTimeout() silently does nothing; no exception is thrown."
   clearTimeout(sockTimer);  
   sockTimer = null;
}


