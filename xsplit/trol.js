/***************************
 * Xsplit control system, this is the part that interfaces with xsplit.  
 *
 * See ka-control2.html for the rest of the xsplit portion, see /brains/ for the server end.
 ***************************/
let xjs = require('xjs');
xjs.ready();

let scenedata  = [];
let camdata    = [];
let data_valid = false;

function receiveCamList(m)
{
   camdata = [];
   for(let c of m['cams'])
   {
      console.log("We learned about a camera named " + c['name']);
      camdata.push(c);
   }
}
sockDispatch("server.camlist", receiveCamList);

async function doSceneChange(m)
{
   for(let x=0; x<scenedata.length;x++)
   {
      if(m['name'] == scenedata[x]['name'])
      {
         console.log("Changing active scene to " + m['name'] + " by request")
         await xjs.Scene.setActiveScene(scenedata[x]['index']+1); // Index=0base, setActiveScene=1base // smh
         return;
      }
   }
   console.log("Requested change to scene " + m['name'] + " but we can't find it.")
}
sockDispatch("request.scenechange", doSceneChange);

async function doPosChange(m)
{
   let pos = m.pos;
   let url = new URL(m.url);
   // This strainge little protocol shuffle is because URL() is broken on rtsp: and won't set username/password
   // but it works if you set it on http then change protocols!
   url.protocol = 'http:';
   url.username = CONFIG.CAMUSER;
   url.password = CONFIG.CAMPASS;
   url.protocol = "rtsp:";
   // TODO: Let's write more passwords into logs!
   console.log("Request for " + m.cam + " in position " + pos + " using " + url.href);

   let toset = await xjs.Scene.searchItemsByName('TROL ' + pos);
   if(toset.length == 0)
   {
      console.log("Requested position " + pos + " not found.");
      return;
   }

   for(i of toset)
   {
      await i.setValue(url.href);
      console.log("Set a position.");
   }

   sockSend('xsplit.positionchanged', { "cam": m.cam, "pos": pos });
}
sockDispatch("request.positionchange", doPosChange);

// Because of xsplit architecture, all we can do here is decide to show or not show the news scroll.
// separate code in trolscrol.js runs "inside" the scroll to update what the scroll text says.
// there's no way to set the text in the scroll from "outside" and no way to do the rest from "inside" 
// so it's very awkwardly constructed.
async function displayScroll(m)
{
   console.log("Got request to display the scroll.")
   toset = await xjs.Scene.searchItemsByName('TROLSCROL');
   for(i of toset)
      await i.setVisible(true);

   setTimeout(async function endscroll() { 
         toset = await xjs.Scene.searchItemsByName('TROLSCROL');
         for(i of toset)
            await i.setVisible(false);

         console.log("Finished displaying the scroll.")
      // TODO: Set news scroll time better.
      }, 120 * 1000);
}
sockDispatch("news.showscrolldata", displayScroll);

async function serverPong(m)
{
   sockSend("user.pong", { "time": "IDKLOL" });
}
sockDispatch("server.ping", serverPong);

async function onConnect()
{
   update_status("Connected");
   sockSend('user.hello', { "user": "xsplitV2", "cams": true, "news": true });
   await sendTrolData();
   await onSceneChange();
}
sockSetOnConnect(onConnect);

async function onDisconnect()
{
   update_status("Disconnected");
}
sockSetOnDisconnect(onDisconnect);


async function getTrolData()
{
   await xjs.ready();
   let n_scenes = await xjs.Scene.getSceneCount();
   for(let x=0; x<n_scenes; x++)
   {
      let scene = await xjs.Scene.getBySceneIndex(x);
      let sname = await scene.getName();
      console.log(`Scene ${x+1} of ${n_scenes} is ${sname}`);
      let items = await scene.getItems();
      let positions = [];
      for(let i of items)
      {
         p = await i.getCustomName();
         console.log(`Examining item ${p} in scene ${sname}`);
         if(p.startsWith('TROL '))
         {
            p = p.substring(5);
            positions.push(p);
            console.log(`Detected position ${p} in scene ${sname}`);
         }
      }
      scenedata.push({ "name": sname, "positions": positions, "index": x });
   }
   data_valid = true;
}

async function sendTrolData()
{
   if(! data_valid)
      await getTrolData();

   sockSend('xsplit.scenedata', { "scenedata": scenedata });
}

async function onSceneChange()
{
   scene = await xjs.Scene.getActiveScene();
   sname = await scene.getName();
   // console.log("Detected scene change to " + sname);
   sockSend('xsplit.scenechanged', { "name": sname, "scene": sname });
}
xjs.ExtensionWindow.on('scene-load', onSceneChange);

async function isRecording()
{
   // If we are NOT recording, the "Local Recording" output will exist, 
   // but the "Local Recording" channel will not.  
   // If we are recording, they will both exist.
   // If neither one exists, something is really broken.  
   // Like my spirit after trying to code with xjs
   haveOutput = false;
   haveChannel = false;
   await xjs.Output.getOutputList().then(function(outputs) {
      outputs.map(output => {
         output.getName().then(function(name) {
            if(name == "Local Recording")
            {
               haveOutput = true;
               console.log("Got output: " + name);
            }
         })
      })
   })

   await xjs.StreamInfo.getActiveStreamChannels().then(function(channels) {
      channels.forEach(function(channel) {
         channel.getName().then(function(name) {
            if(name == "Local Recording")
            {
               haveChannel = true;
               console.log("Got channel: " + name);
            }
         })
      })
   })

   if(!haveOutput)
      console.log("ERROR: We don't have a recording output.");

   if(haveChannel)
   {
      console.log("We are recording.");
      update_status("RECORDING");
      return true;
   }
   update_status("recording ended");
   console.log("We are NOT recording.");
   return false;
}


async function requestRecording(m)
{
   if("record" in m)
   {
      let wasrecording = isRecording();
      if(m["record"])
      {
         if(wasrecording)
         {
            console.log("Request to start recording but we already were - this is a Big Deal please do something.");
            sockSend('xsplit.exception', { "text": "Request to start recording but we already were - this is a Big Deal please do something." });
         }
         console.log("Starting recording.")
         await xjs.Output.startLocalRecording();
      }
      else
      {
         if(! wasrecording)
         {
            console.log("Request to stop recording but we weren't");
         }
         console.log("Stopping recording.")
         await xjs.Output.stopLocalRecording();
      }
   }
   sockSend('xsplit.recording', { "recording": isRecording() });
}
sockDispatch("request.recording", requestRecording);
// request.recording returns recording status, optionally if you call it with "record": True it starts recording and "record": False stops.


async function testButtonClick()
{
   await xjs.ready();
   /*
   let items = await xjs.Scene.searchItemsByName('TROLSCROL');
   let item = items[0];
   let conf = await item.loadConfig();
   console.log(JSON.stringify(conf));
   conf.text = "wtf xjs lol idk";
   await item.applyConfig(conf);
   await item.requestSaveConfig(conf);
   //const { _id } = item;
   //let attached = await xjs.exec('SearchVideoItem2', _id);
   //await xjs.exec('SetLocalPropertyAsync2', 'prop:BrowserConfiguration', JSON.stringify(conf));
   */
}

