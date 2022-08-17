/***************************************
 * Websocket client with Trol-specific message callbacks
 ***************************************/


// State used by sockReconnect() below
let sock = sockCreate();
let sockFails = 0;
let sockTimer = null;
let sockDispatchDict = {};
let sockOnConnect = null;
let sockOnDisconnect = null;

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
         sock = sockCreate();
      }

      // multiplicative backoff tops out at 5 seconds
      sockFails++;
      let mult = (sockFails > 5) ? 5 : sockFails;
      clearTimeout(sockTimer);
      sockTimer = setTimeout(_sr, delay = 1000 * mult);
   }
   _sr();
}

function sockCreate() 
{
   s = new WebSocket(CONFIG.WSURI);
   s.addEventListener('close', sockHandleClose);
   s.addEventListener('open', sockHandleOpen); 
   s.addEventListener('message', sockHandleMessage);
   return s;
}

// The close event is emitted if we fail to connect in the first place too
function sockHandleClose(ev)
{
	console.log("Server disconnect.");
   if(sockOnDisconnect !== null)
   {
      sockOnDisconnect();
   }
   sockReconnect();
}

function sockHandleOpen(ev)
{
	console.log("Server connect.");
   // Since we just got a good connection let's reset any connection attempts in progress
   sockStopReconnect();
   if(sockOnConnect !== null)
      sockOnConnect();
}

function sockStopReconnect()
{
   if(sock.readyState != 1) // Magic number 1 means connected
      console.log("Stopping connecting even though socket state is " + sock.readyState);

   clearTimeout(sockTimer);
   sockFails = 0;
}

function sockHandleMessage(ev)
{
   let d = {};
   try {
      d = JSON.parse(ev.data);
   } 
   catch(e) {
      console.log("Got bad data from server: " + ev.data);
      return;
   }

   let mtype = d['mtype'];
   if(! mtype)
   {
      console.log("Missing mtype in message: " + ev.data);
      return;
   }

   if(mtype in sockDispatchDict)
      sockDispatchDict[mtype](d);
   else
      console.log("Got unexpected mtype: " + mtype + " in message " + ev.data);
}

function sockSend(mtype, data)
{
   if(sock.readyState != 1)
      console.log("Trying to send " + mtype + " but websock isn't ready.");
   data['mtype'] = mtype;
   return sock.send(JSON.stringify(data));
}

function sockDispatch(mtype, fn)
{
   sockDispatchDict[mtype] = fn;
}

function sockSetOnConnect(fn)
{
   sockOnConnect = fn;
}

function sockSetOnDisconnect(fn)
{
   sockOnDisconnect = fn;
}
