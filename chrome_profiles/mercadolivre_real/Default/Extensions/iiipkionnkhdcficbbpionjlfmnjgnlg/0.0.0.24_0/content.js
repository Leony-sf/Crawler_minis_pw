(function() {
  "use strict";

  var pageToContent = document.createElement("button");
  pageToContent.style.display = "none";
  pageToContent.id = "pageToContentId";
  (document.head || document.documentElement).appendChild(pageToContent);

  // Listener of inject.js
  pageToContent.addEventListener("click", function(event) {

    var messageToBackground = {
      "extId": pageToContent.getAttribute("extId"),
      "type": "networkData",
      "params": pageToContent.getAttribute("params")
    };
    // send to background.js
    chrome.runtime.sendMessage(messageToBackground, function(response) {
      // send to inject.js
      var contentToPage = document.getElementById("contentToPageId");
      contentToPage.setAttribute("extId", response.extId);
      contentToPage.setAttribute("xhrAllowed", response.params.xhrAllowed);
      contentToPage.setAttribute("uniqueId", response.id);
      contentToPage.click();
    });
  });

  var contentToPage = document.createElement("button");
  contentToPage.style.display = "none";
  contentToPage.id = "contentToPageId";
  (document.head || document.documentElement).appendChild(contentToPage);

  var script = document.createElement("script");
  script.type = "application/javascript";
  script.async = false;
  script.src = chrome.extension.getURL('inject.js');
  script.onload = function() {
      this.parentNode.removeChild(this);
  };
  (document.head || document.documentElement).appendChild(script);
})();

