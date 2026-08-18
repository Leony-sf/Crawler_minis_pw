(function() {
  "use strict";

  var logLevel = 1;

  console.log("Data leakage prevention for chrome is on!");
  
  if( window !== window.top ) {
      if (logLevel <= 1) {
        console.log("Enter iframe!");
      }
  }


  function generateRamdomNumber() {
    return parseInt(Math.random() * 1000000, 10);
  }

  function generateUniqueId(url) {
    var uniqueId = "";
    var timeStamp = new Date().getTime();
    do {
      uniqueId = url + timeStamp + generateRamdomNumber();
    } while (xhrMap.has(uniqueId))
    return uniqueId;
  }

  function plainData(args) {
    var result = {};
    result.unstructed = "";
    result.inspect_type = 1;
    if (args instanceof Array) {
      result.streamContent = args.toString();
    } else if (args instanceof Object) {
      result.streamContent = JSON.stringify(args);
    }
    //result.streamContent = "Unstructed data!"
    return JSON.stringify(result);
  }

  function initStructedData(mail_vendor, url) {
    var result = {};
    result.structed = "";
    result.browser_type = 1;
    result.sender = "";
    result.inspect_type = 0;
    if (typeof url === "string")
      result.url = url;
    else
      result.url = "unknown";
    result.request_url = url;
    result.subject = "";
    result.recipent = "";
    result.msg_body = "";
    result.attach_name = "";
    result.bccRecipent = "";
    if (typeof mail_vendor === "string")
      result.mail_vendor = mail_vendor;
    else
      result.mail_vendor = "unknown";
    return result;
  }
  
  function FilterData(type, url, args) {

    if (type === "XMLHttpRequest") {
      if (!args || !args[0]) {
        return plainData(args);
      }

      var gmailPattern = /https:\/\/mail.google.com\/*/;
      var outlookPattern = /https:\/\/outlook.live.com\/mail\/*/;
      var aolPattern = /https:\/\/mail.aol.com\/webmail\/*/;
      var yahooPattern = /https:\/\/mail.yahoo.com\/*/;

      if (gmailPattern.test(window.location.href)) {
        if (typeof args[0] !== "string") {
          return plainData(args);
        }

        var argsObj;
        try {
          argsObj = JSON.parse(args[0]);
        } catch (e) {
          return plainData(args);
        }

        var argsInternal;
        if (argsObj &&
          argsObj["2"] &&
          argsObj["2"]["1"] &&
          argsObj["2"]["1"][0] &&
          argsObj["2"]["1"][0]["2"] &&
          argsObj["2"]["1"][0]["2"]["2"] &&
          argsObj["2"]["1"][0]["2"]["2"]["3"] &&
          argsObj["2"]["1"][0]["2"]["2"]["3"]["1"] &&
          argsObj["2"]["1"][0]["2"]["2"]["3"]["1"]["5"] &&
          argsObj["2"]["1"][0]["2"]["2"]["3"]["1"]["5"][0]) {
          argsInternal = argsObj["2"]["1"][0]["2"]["2"]["3"]["1"]["5"][0];
        } else if (argsObj &&
                    argsObj["2"] &&
                    argsObj["2"]["1"] &&
                    argsObj["2"]["1"][0] &&
                    argsObj["2"]["1"][0]["2"] &&
                    argsObj["2"]["1"][0]["2"]["2"] && 
                    argsObj["2"]["1"][0]["2"]["2"]["14"]&&
                    argsObj["2"]["1"][0]["2"]["2"]["14"]["1"]){
          argsInternal = argsObj["2"]["1"][0]["2"]["2"]["14"]["1"];
        } else if (argsObj &&
                    argsObj["2"] &&
                    argsObj["2"]["1"] &&
                    argsObj["2"]["1"][0] &&
                    argsObj["2"]["1"][0]["2"] &&
                    argsObj["2"]["1"][0]["2"]["2"] && 
                    argsObj["2"]["1"][0]["2"]["2"]["2"]&&
                    argsObj["2"]["1"][0]["2"]["2"]["2"]["1"]){
          argsInternal = argsObj["2"]["1"][0]["2"]["2"]["2"]["1"];
        }
        if (argsInternal) {
          var result = initStructedData("gmail", url);

          if (argsInternal["2"])
            result.sender = argsInternal["2"]["2"] ? argsInternal["2"]["2"] : "";
          if (argsInternal["3"]) {
            var recipentsArray = argsInternal["3"];
            Array.prototype.forEach.call(recipentsArray, (currentValue) => {
              result.recipent += currentValue["2"] + ";";
            });
          }
          if (argsInternal["4"]) {
            var attach_nameArray = argsInternal["4"];
            Array.prototype.forEach.call(attach_nameArray, (currentValue) => {
              result.attach_name += currentValue["2"] + ";";
            });
          }
          if (argsInternal["5"]) {
            var bccRecipentArray = argsInternal["5"];
            Array.prototype.forEach.call(bccRecipentArray, (currentValue) => {
              result.bccRecipent += currentValue["2"] + ";";
            });
          }
          result.subject = argsInternal["8"] ? argsInternal["8"] : "";
          if (argsInternal["9"] && argsInternal["9"]["2"]) {
            var msg_bodyArray = argsInternal["9"]["2"];
            Array.prototype.forEach.call(msg_bodyArray, (currentValue) => {
              result.msg_body += currentValue["2"].replace(/<[^>]*>|/g,"") + ";";
            });
          }
          return JSON.stringify(result);
        } else {
          return plainData(args);
        }
      } else if (outlookPattern.test(window.location.href)) {
        return plainData(args);
      } else if (aolPattern.test(window.location.href)) {
        var rawString = decodeURIComponent(args[0].split('&')[0].split('=')[1]);
        var jsonString = rawString.slice(1, -1);
        var content;
        try {
          content = JSON.parse(jsonString);
        } catch (e) {
          return plainData(args);
        }
        if (!content.To)
          return plainData(args);

        var result = initStructedData("aol", url);
        result.subject = content.Subject;
        result.sender = content.From;
        result.recipent = content.To;
        result.bccRecipent = content.Bcc;
        result.msg_body = content.PlainBody;
        result.attach_name = content.Cc;
        return JSON.stringify(result);

      } else if (yahooPattern.test(window.location.href)) {
        if (args[0] instanceof FormData) {
          var batchJson = args[0].get("batchJson");
          if (!batchJson)
            return plainData(args);
          var batchJsonReal;
          try {
            batchJsonReal = JSON.parse(batchJson);
          } catch (e) {
            return plainData(args);
          }

          if (!batchJsonReal || !batchJsonReal.requests || !batchJsonReal.requests[0] || !batchJsonReal.requests[0].payloadParts || !batchJsonReal.requests[0].payloadParts[0] || !batchJsonReal.requests[0].payloadParts[0].payload || !batchJsonReal.requests[0].payloadParts[0].payload.message)
            return plainData(args);
          
          var message = batchJsonReal.requests[0].payloadParts[0].payload.message;
          var result = initStructedData("yahoo", url);

          result.subject = message.headers.subject;
          Array.prototype.forEach.call(message.headers.from, (currentValue) => {
            result.sender += currentValue.email + ";";
          });
          Array.prototype.forEach.call(message.headers.to, (currentValue) => {
            result.recipent += currentValue.email + ";";
          });
          Array.prototype.forEach.call(message.headers.cc, (currentValue) => {
            result.attach_name += currentValue.email + ";";
          });
          Array.prototype.forEach.call(message.headers.bcc, (currentValue) => {
            result.bccRecipent += currentValue.email + ";";
          });
          result.msg_body = batchJsonReal.requests[0].payloadParts[0].payload.simpleBody.html.replace(/<[^>]*>|/g,"");

          return JSON.stringify(result);
        }
      }

      return plainData(args);
    } else if (type === "fetch") {
      if (url === "/owa/service.svc?action=CreateItem&app=Mail") {
        if (!args || !args.body)
          return plainData(args);
        var body;
        try {
          body = JSON.parse(args.body);
        } catch (e) {
          return plainData(args); 
        }

        if (!body || !body.Body || !body.Body.Items)
          return plainData(args);

        var result = initStructedData("outlook", url);

        var items = body.Body.Items;
        Array.prototype.forEach.call(items, (item) => {
          result.subject = item.Subject; // items may be more than 2?
          Array.prototype.forEach.call(item.ToRecipients, (recipient) => {
            result.recipent += recipient.EmailAddress + ";";
          });
          Array.prototype.forEach.call(item.CcRecipients, (recipient) => {
            result.attach_name += recipient.EmailAddress + ";";
          });
          if (item.Body && item.Body.Value)
            result.msg_body = item.Body.Value.replace(/<[^>]*>|/g,"");
          else if (item.NewBodyContent && item.NewBodyContent.Value)
            result.msg_body = item.NewBodyContent.Value.replace(/<[^>]*>|/g,"");
          else
            console.log("Create item shouldn't get in!");
        })

        return JSON.stringify(result);
      } else if (url === "/owa/service.svc?action=UpdateItem&app=Mail") {
        if (!args || !args.body)
          return plainData(args);
        var body;
        try {
          body = JSON.parse(args.body);
        } catch (e) {
          return plainData(args); 
        }

        if (!body || !body.Body || !body.Body.ItemChanges || !body.Body.ItemChanges[0] || !body.Body.ItemChanges[0].Updates)
          return plainData(args);

        var result = initStructedData("outlook", url);
        var items = body.Body.ItemChanges[0].Updates;
        Array.prototype.forEach.call(items[0].Item.ToRecipients, (recipient) => {
          result.recipent += recipient.EmailAddress + ";";
        });
        Array.prototype.forEach.call(items[1].Item.CcRecipients, (recipient) => {
          result.attach_name += recipient.EmailAddress + ";";
        });
        Array.prototype.forEach.call(items[2].Item.BccRecipients, (recipient) => {
          result.bccRecipent += recipient.EmailAddress + ";";
        });
        result.subject = items[3].Item.Subject;
        if (items[4].Item.Body && items[4].Item.Body.Value)
          result.msg_body = items[4].Item.Body.Value.replace(/<[^>]*>|/g,"");
        else
          console.log("Update item shouldn't get in!")

        return JSON.stringify(result);

      }
      return plainData(args);
    }

  }








  var xhrMap = new Map();
  var checkUnstructed = false;

  var hookFetch = function(obj) {
    if (window.fetch) {
      var realFetch = window.fetch;
      var interceptorBefore = obj.interceptorBefore;
      window.fetch = function (url, options = {}) {
        if (options && options.method && options.method.toString().toLowerCase() === "post") {
          var that = this;
          return new Promise((resolve, reject) => {
            if (!interceptorBefore(url, options, realFetch, that, resolve, reject))
              realFetch.call(that, url, options)
              .then((res) => {
                resolve(res);
              })
              .catch((err) => {
                reject(err);
              });
          });
        } else {
          return realFetch(url, options);
        }
      }
    }  
  }

  hookFetch({
    "interceptorBefore": function(url, options, realFetch, that, resolve, reject) {

      // Send to content.js
      var params = FilterData("fetch", url, options);
      if (!checkUnstructed && JSON.parse(params).unstructed === "")
          return false;
      if (logLevel <= 1)
        console.log("url: ", url);
      var pageToContent = document.getElementById("pageToContentId");
      var extId = generateUniqueId(window.location.href);
      xhrMap.set(extId, ["fetch", url, options, realFetch, that, resolve, reject]);
      pageToContent.setAttribute("extId", extId);
      pageToContent.setAttribute("params", params);
      pageToContent.click();
      return true;
    }
  });


  var hookAjax = function (proxy) {
    window._ahrealxhr = window._ahrealxhr || XMLHttpRequest;
    XMLHttpRequest = function () {
      this.xhr = new window._ahrealxhr;
      for (var attr in this.xhr) {
        var type = "";
        try {
          type = typeof this.xhr[attr]
        } catch (e) {}
        if (type === "function") {
          this[attr] = hookfun(attr);
        } else {
          Object.defineProperty(this, attr, {
            get: getFactory(attr),
            set: setFactory(attr)
          })
        }
      }
    };

    function hookfun(fun) {
      return function () {
        var args = [].slice.call(arguments);
        if (proxy[fun] && proxy[fun].call(this, args, this.xhr)) {
          return;
        }
        return this.xhr[fun].apply(this.xhr, args);
      }
    };

    function getFactory(attr) {
      return function () {
        var v= this.hasOwnProperty(attr + "_") ? this[attr + "_"] : this.xhr[attr];
        var attrGetterHook = (proxy[attr] || {})["getter"];
        return attrGetterHook && attrGetterHook(v,this) || v;
      }
    }

    function setFactory(attr) {
      return function (v) {
        var xhr = this.xhr;
        var that = this;
        var hook = proxy[attr];
        if (typeof hook === "function") {
          xhr[attr] = function () {
            proxy[attr](that) || v.apply(xhr, arguments);
          }
        } else {
          var attrSetterHook=(hook || {})["setter"];
          v = attrSetterHook && attrSetterHook(v, that) || v
          try {
            xhr[attr] = v;
          }catch(e) {
            this[attr + "_"] = v;
          }
        }
      }
    }

    return window._ahrealxhr;
  };

  hookAjax({
    open:function(args,xhr){
      var method = args[0] ? args[0].toString().toLowerCase() : '';
      var url = args[1] ? args[1] : '';
      var async = args[1] ? args[1] : '';
      if (async === false && logLevel <= 3)
        console.log("Synchronization request url: ", url);
      if (method === "post") {
        xhr.requestParams = {};
        xhr.requestParams.method = method;
        xhr.requestParams.url = url;
        xhr.requestParams.async = async;
      }

      return false;
    },
    send: function(args, xhr){
      if (xhr && xhr.requestParams && xhr.requestParams.method === "post") {
        // Send to content.js
        var params = FilterData("XMLHttpRequest", xhr.requestParams.url, args);
        if (!checkUnstructed && JSON.parse(params).unstructed === "")
          return false;
        if (logLevel <= 1)
          console.log("url: ", xhr.requestParams.url);
        var pageToContent = document.getElementById("pageToContentId");
        var extId = generateUniqueId(window.location.href);
        xhrMap.set(extId, ["XMLHttpRequest", this.xhr, args]);
        pageToContent.setAttribute("extId", extId);
        pageToContent.setAttribute("params", params);
        pageToContent.click();
        return true;
      }
      
      return false;
    },
    timeout: {
      setter: function (v, xhr) {
        return Math.max(v, 1000);
      }
    }
  });







  // Listener of content.js
  document.getElementById("contentToPageId").addEventListener("click", function(event) {
    var contentToPage = document.getElementById("contentToPageId");
    var extId = contentToPage.getAttribute("extId");
    var xhrAllowed = contentToPage.getAttribute("xhrAllowed");
    var uniqueId = contentToPage.getAttribute("uniqueId");
    var xhrObjectAndArgs = xhrMap.get(extId);
    xhrMap.delete(extId);

    if (xhrObjectAndArgs[0] === "XMLHttpRequest") {
      if (logLevel <= 2) {
        console.log("(Id " + uniqueId + ") XMLHttpRequest raw data is: ");
        console.log(xhrObjectAndArgs[2]);
      }
      
      if (xhrAllowed == 'true') {
        xhrObjectAndArgs[1]["send"].apply(xhrObjectAndArgs[1], xhrObjectAndArgs[2]);
      } else {
        xhrObjectAndArgs[1]["abort"].apply(xhrObjectAndArgs[1]);
      }
    } else if (xhrObjectAndArgs[0] === "fetch") {
      if (logLevel <= 2) {
        console.log("Id " + uniqueId + " fetch raw data is: ");
        console.log(xhrObjectAndArgs[2]);
      }
      if (xhrAllowed == 'true') {
        xhrObjectAndArgs[3].call(xhrObjectAndArgs[4], xhrObjectAndArgs[1], xhrObjectAndArgs[2])
        .then((res) => {
          xhrObjectAndArgs[5](res);
        })
        .catch((err) => {
          xhrObjectAndArgs[6](err);
        });
      } else {
        xhrObjectAndArgs[6](new Error("Sensitive data found!"));
      }
    }
  });
})();
