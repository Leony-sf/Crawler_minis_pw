"use strict";

console.log("Data leakage prevention for chrome is on!");

import { generateRamdomNumber, generateTimeString, sendNativeMessage } from './utils.js';

/* //remove dlp
var uniqueIdMap = new Map();
var expireMap = new Map();
//var chrome = browser;*/

export async function collectWtpPtInfo(uniqueId, ptParams, ptLog){
  console.log("[collectWtpPtInfo] message is " + ptLog);
  var message = {
    id: uniqueId,
    type: "wtpPT",
    params: ptParams,
    log: ptLog,
    date: generateTimeString()
  };
  await sendNativeMessage(message);
}

/* //remove dlp
var expireInterval = 2400;
var expireTimer = window.setInterval(()=>{
  Map.prototype.forEach.call(expireMap, (currentValue, currentKey) => {
    if (currentValue < new Date().getTime()) {
      var id = uniqueIdMap.get(currentKey);
      var sendResponse = sendResponseMap.get(currentKey);
      var message = {id: currentKey, params: {xhrAllowed: "true"}, extId: id};
      sendResponse(message);
      message.date = generateTimeString();
      console.log("Connecting to native messaging host timeout! Message: ", message)
      uniqueIdMap.delete(currentKey);
      sendResponseMap.delete(currentKey);
      expireMap.delete(currentKey);
    }
  });
}, 200);
*/

(async function () {
    var uniqueId = generateRamdomNumber();
    var message = {
        id: uniqueId,
        type: "process",
    };
    console.log("Background.js startup and send native app: ", message)
    await sendNativeMessage(message);

})();