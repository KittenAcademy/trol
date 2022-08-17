/******************************
 * This class displays a list of images at a given scale, with labels, overlays, etc
 *
 * It's a mess that was probably good for me to learn something about JS but now has become big enough
 * that it feels like something I should be pulling from an established widget framework
 * 
 * No, I don't remember what TAI was supposed to stand for.  
 ******************************/
class TAI 
{
   // TODO: God as my witness I thought we were using Python with named parameters.
   constructor(name, framecount = 1, safeclicks = 0, enablemulti = false,
               w=1920/8, h=1080/8, itemlist=[])
   {
      this.name   = name;
      this.width  = w;
      this.height = h;
      this.items  = itemlist ?? [];
      // framecount = number of images to keep and animate through at 1fps
      this.framecount   = framecount;
      // framenum       = current animation frame
      this.framenum     = 0;
      // overlays displayed over image if selected or active
      this.selectedurl      = "img/selected.png";
      this.multiselectedurl = "img/multiselected.png";
      this.activeurl        = "img/active.png";
      // variables to hold actual selection data
      this.selected        = null;
      this.multiselected   = [];
      this.active          = null;
      this.selclicks       = 0;
      // enable multiple selection
      this.enablemulti     = enablemulti;
      // enable 'safe clicks' -- currently implemented as requiring 5 clicks to select
      this.safeclicks      = safeclicks;

      // Set up the item data a bit if it's not
      let icnt = 0;
      for(i of this.items)
      {
         icnt += 1;
         i.name = i.name ?? "item"+icnt;
         this.initItem(i);
      }

      if(this.framecount > 1) this.animationInterval = setInterval(this.animateImages.bind(this), 1000);
   }

   // Why isn't item also a class?
   initItem(i)
   {
      // When the properties i.ul, i.ur, etc are set, also change the text in the corresponding div.
      for(let p of ["ul","ur","ll","lr"])
      {
         function makesetter(i,p) { return function(v) { i["__" + p] = v; if(i[p + "div"]) i[p + "div"].innerHTML = v; } };
         function makegetter(i,p) { return function() { return i["__" + p]; } };

         let tv = i[p] ?? "";
         i[p] = undefined;
         Object.defineProperty(i, p, 
            { "set": makesetter(i,p),
              "get": makegetter(i,p)
            });
         i[p] = tv;
      }
      // When the properties active, selected, multiselected are set, also hide/unhide the overlay
      for(let o of ["active", "selected", "multiselected"])
      {
         let tv = i[o] ?? false;
         i[o] = undefined;
         Object.defineProperty(i, o,
            {  "set": function (i, o) { return function(v) { i["__" + o] = v; if(i[o + "ovl"]) i[o + "ovl"].hidden = !v; } }(i,o),
               "get": function (i, o) { return function() { return i["__" + o] } }(i,o) 
            });
         i[o] = tv;
      }

      i.toString = function() { return i.name; };

      i.imgs = i.imgs ?? [];
      return i;
   }

   addItem(item = {})
   {
      if (! item.name)
         item.name = "item" + this.items.length;

      item = this.initItem(item);
      this.items.push(item);
      return item;
   }

   getItem(name)
   {
      for(let i of this.items)
         if(i.name === name)
            return i;
      return undefined;
   }

   // We always put the newest frame in [0] so we have to animate backwards
   addImage(name, idat)
   {
      let i = this.getItem(name);
      i.imgs.unshift(idat);
      i.imgs.splice(this.framecount);
   }

   animateImages()
   {
      this.framenum = this.framenum - 1;
      if(this.framenum < 0) this.framenum = this.framecount - 1

      for(let i of this.items)
      {
         let fnum = (i.imgs.length - 1 < this.framenum) ? i.imgs.length - 1 : this.framenum;
         if(fnum >= 0)
         {
            i.img.setAttribute('src', i.imgs[fnum]);
         }
         else
            console.log("No image for item " + i.name + " in " + this.name);
      }
   }

   handleClick(name, ev)
   {
      // Really coded into a corner here when I found out mobile doesn't have great support for right clicks or double clicks... ugh.

      let nclicks = ev.detail; // OS-defined counter for double, triple clicks.
      // console.log("Detected " + ev.detail + " clicks");
      let i = this.getItem(name);
      if(! i)
      {
         console.log("Can't service click for " + name);
         return;
      }

      let oldsel = this.selected;
      this.selected = name;

      // console.log("Got click for " + name + " oldsel: " + oldsel + " enablemulti: " + this.enablemulti + " nclicks: " + nclicks + " ms: " + this.multiselected.length + " " + this.multiselected);

      // Require multiple clicks to activate
      if(this.safeclicks > 1)
      {
         if(oldsel != name)
         {
            let os = this.getItem(oldsel);
            if(os)
               this.clearSelection(os);
            i.clicks = 1;
            i.ll = this.safeclicks - i.clicks + " clicks to go";
         }
         else
         {
            i.clicks += 1;
            i.ll = this.safeclicks - i.clicks + " clicks to go";
            if(i.clicks == this.safeclicks)
            {
               i.selected = true;
               i.ll = "";
               // if the selection callback returns true, clear the selection.
               if(this.selectedCallback(i, this))
               {
                  this.clearSelection();
               }
            }
            if(i.clicks > this.safeclicks) // If we keep clicking after selection, cancel.
            {
               this.clearSelection();
            }
         }
      }
      else if(this.multiselected.length > 0)
      {
         this.selected = null;
         if(nclicks > 1)
         {
            // console.log("Canceling multi");
            this.clearMultiselection();
            return
         }
         if(this.multiselected.indexOf(i) > -1) // Already selected
         {
            // console.log("Deselecting multi " + i.name);
            i.multiselected = false;
            this.multiselected.splice(this.multiselected.indexOf(i), 1);
         }
         else
         {
            // console.log("Adding multi " + i.name);
            i.multiselected = true;
            this.multiselected.push(i);
         }
      }
      else // Regular clicks
      {
         if(oldsel)
            this.getItem(oldsel).selected = false;

         if(nclicks > 1 && this.enablemulti)
         {
            i.multiselected = true;
            this.multiselected.push(i);
            this.selected = null;
            return
         }

         if(oldsel == name)
         {
            // This would indicate a double-click so this is where we'd go to multimode if needed.
            this.selected = null;

            if(this.enablemulti)
            {
               // TODO: Detect we're on a system that can't double-click (like mobile) and only
               // do this if we are
               i.multiselected = true;
               this.multiselected.push(i);
               return;
            }
         }
         else // New selection
         {
            i.selected = true;
            if(this.selectedCallback(i, this))
               this.clearSelection();
         }
      }
   }

   clearSelection(i = null)
   {
      // if we aren't passed an item, clear everything
      // if we are passed an item, only clear data in that item
      if(i === null)
      {
         i = this.getItem(this.selected);
         this.selected = null;
      }
      if(! i)
      {
         // console.log("No selection in " + this.name);
         return;
      }

      if(this.safeclicks > 1)
      {
         i.clicks = 0;
         i.ll = "";
      }
      i.selected = false;
   }

   clearMultiselection()
   {
      let names = [];
      for(let i of this.multiselected)
      {
         names.push(i.name);
         i.multiselected = false;
      }
      this.multiselected = [];
      return names;
   }

   clearActive()
   {
      for(let i of this.items)
         i.active = false;
      this.active = null;
   }

   createElement()
   {
		let cont = document.createElement("div");
      cont.setAttribute('id', this.name + "_container");
      cont.setAttribute('class', "tai_container");

      for(let i of this.items)
      {
         let z = 0; 
         // console.log("Displaying item: " + JSON.stringify(i));
         // item div
         let d0 = cont.appendChild(document.createElement("div"));
         d0.setAttribute("id", i.name + "_div0");
         d0.setAttribute("class", "tai_div0 ");
		   d0.setAttribute('style', `float: left; position: relative; z-index:${z++}; color: white; text-shadow: 0 0 4px black, 0 0 2px black, 0 0 2px black;`);
         d0.addEventListener("click", this.handleClick.bind(this, i.name));
         // item image - animate if multiple
         let el = d0.appendChild(document.createElement("img"));
		   // el.setAttribute('style', `position: absolute; z-index:${z++}; top: 0; right: 0;`);
         el.setAttribute("id", i.name + "_img");
         el.setAttribute("class", "tai_img");
         el.setAttribute("alt", i.name);
         el.setAttribute("width", this.width);
         el.setAttribute("height", this.height);
         el.setAttribute("name", i.name);
         if(i.imgs.length)
         {
            el.setAttribute("src", i.imgs[0]);
         }
         i.img = el;
         // overlay images - stack if multiple
         if(i.overlays)
         {
            let ocnt = 0;
            for(ovl of i.overlays)
            {
               el =  d0.appendChild(document.createElement("img"));
               el.setAttribute('style', `position: absolute; z-index:${z++}; top: 0; right: 0;`);
               el.setAttribute("id", i.name + "_ovl" + ocnt);
               el.setAttribute("class", "tai_ovl" + ocnt + " " + i.name + "_ovl" + ocnt);
               el.setAttribute("width", this.width);
               el.setAttribute("height", this.height);
               el.setAttribute("name", i.name);
               el.setAttribute("src", ovl);
            }
         }

         // selected item overlay
         el =  d0.appendChild(document.createElement("img"));
         el.setAttribute('style', `position: absolute; z-index:${z++}; top: 0; right: 0;`);
         el.setAttribute("id", i.name + "_sel");
         el.setAttribute("class", "tai_sel " + i.name + "_sel");
         el.setAttribute("width", this.width);
         el.setAttribute("height", this.height);
         el.setAttribute("name", i.name);
         el.setAttribute("src", this.selectedurl);
         el.hidden = true;
         i.selectedovl = el;

         // multi-selected item overlay
         el =  d0.appendChild(document.createElement("img"));
         el.setAttribute('style', `position: absolute; z-index:${z++}; top: 0; right: 0;`);
         el.setAttribute("id", i.name + "_msel");
         el.setAttribute("class", "tai_msel " + i.name + "_msel");
         el.setAttribute("width", this.width);
         el.setAttribute("height", this.height);
         el.setAttribute("name", i.name);
         el.setAttribute("src", this.multiselectedurl);
         el.hidden = true;
         i.multiselectedovl = el;

         // active item overlay
         el =  d0.appendChild(document.createElement("img"));
         el.setAttribute('style', `position: absolute; z-index:${z++}; top: 0; right: 0;`);
         el.setAttribute("id", i.name + "_act");
         el.setAttribute("class", "tai_act " + this.name + "_act");
         el.setAttribute("width", this.width);
         el.setAttribute("height", this.height);
         el.setAttribute("name", i.name);
         el.setAttribute("src", this.activeurl);
         el.hidden = true
         i.activeovl = el;

         // text positions
         el =  d0.appendChild(document.createElement("div"));
         el.setAttribute('style', `position: absolute; z-index:${z++}; top: 5px; left: 10px; text-align:left;`);
         el.setAttribute("id", i.name + "_ul");
         el.setAttribute("class", "tai_ul " + this.name + "_ul");
         el.innerHTML = i.ul;
         i.uldiv = el;
         el =  d0.appendChild(document.createElement("div"));
         el.setAttribute('style', `position: absolute; z-index:${z++}; top: 5px; right: 10px; text-align:right;`);
         el.setAttribute("id", i.name + "_ur");
         el.setAttribute("class", "tai_ur " + this.name + "_ur");
         el.innerHTML = i.ur;
         i.urdiv = el;
         el =  d0.appendChild(document.createElement("div"));
         el.setAttribute('style', `position: absolute; z-index:${z++}; bottom: 5px; left: 10px; text-align:left;`);
         el.setAttribute("id", i.name + "_ll");
         el.setAttribute("class", "tai_ll " + this.name + "_ll");
         el.innerHTML = i.ll;
         i.lldiv = el;

         el =  d0.appendChild(document.createElement("div"));
         el.setAttribute('style', `position: absolute; z-index:${z++}; bottom: 5px; right: 10px; text-align:right;`);
         el.setAttribute("id", i.name + "_lr");
         el.setAttribute("class", "tai_lr " + this.name + "_lr");
         el.innerHTML = i.lr;
         i.lrdiv = el;
      }
      return cont;
   }
}

