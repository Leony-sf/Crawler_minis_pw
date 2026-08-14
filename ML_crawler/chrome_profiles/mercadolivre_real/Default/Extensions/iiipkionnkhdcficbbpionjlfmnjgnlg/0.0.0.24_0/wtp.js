(function() {
  /**
   * Check and set a global guard variable.
   * If this content script is injected into the same page again,
   * it will do nothing next time.
   */
  if (window.hasRun) {
    return;
  }
  window.hasRun = true;


  /*
  * handle the rating result.
  */
  function handleResponse(message) {
    console.log("handleResponse");

    var file_name = chrome.i18n.getMessage("wtp_block_file"); 
    console.log("file_name is " + file_name);
    var path = chrome.runtime.getURL(file_name);
    console.log("path is " + path);
    //document.write(JSON.loads(message.retdata));
    console.log('type of tmext is ' + typeof(TMExt_$));
    console.log('type of message is ' + typeof(message));
    console.log('message.data is ' + message.databc);

    //var htmlObj = document.getElementsByTagName("html")[0];
    //htmlObj.innerHTML = message.databc;

    //window.location.replace(chrome.runtime.getURL('block.html') + "?code=" + window.btoa(message.databc));

    if(document.contentType == "application/xml")
    {
      // if ( window !== window.parent )
      // {
      //   // replace xml with custom xml object within iframe
      //   var newXML = '<?xml version="1.0" encoding="UTF-8"?><Message>Blocked by Trend Micro Web Reputation Service</Message>';
      //   var parser = new DOMParser();
      //   var newDoc = parser.parseFromString(newXML, "text/xml");

      //   // Clear the current document
      //   while (document.firstChild) {
      //       document.removeChild(document.firstChild);
      //   }

      //   // Import nodes from the new document to the current document
      //   for (let i = 0; i < newDoc.childNodes.length; i++) {
      //       document.appendChild(document.importNode(newDoc.childNodes[i], true));
      //   }
      // }
      // else
      // {
      //   // main frame
      //   window.location.replace(chrome.runtime.getURL('block_page.html'));
      // }
      window.location.replace(chrome.runtime.getURL('block_page.html'));
    }
    else
    {
      if(!document.body)document.body = document.createElement("body")
      var htmlObj = document.getElementsByTagName("html")[0];
      htmlObj.innerHTML = message.databc;
      window.stop();
    }

  }

  /*
  * handle the rating error.
  */
  function handleError(error) {
    console.log(`Error: ${error}`);
  }

  /*
  * send current host url to background script for rating
  *
  */
 var sending = chrome.runtime.sendMessage({
      "type": "wtpData",
      "params": {url:document.location.href}
  },function(response) {
    handleResponse(response);
  });

})();
