"use strict";
import { getCurrentPage, collateUploadData, collateDownloadData } from './ddr_bg.js';
import { collectWtpPtInfo } from './wtp_bg.js';
import { generateRamdomNumber, generateTimeString, sendNativeMessage, getEnableStatus } from './utils.js';

// var sendResponseMap = new Map();
// var mapSizeKey = "mapSize"
var mapSizeValue = undefined
const CACHE_DURATION_IN_MS = 600000; // 10 minute (adjust as needed)
const enableFeature = false

////////////////////
// Initial Block // 
////////////////////

chrome.runtime.onInstalled.addListener(() => {
  // Set initial data
  chrome.storage.local.set({ enable: enableFeature }, () => {
    console.log("Default settings initialized.");
  });
});

////////////////////
// Download Block // 
////////////////////
chrome.downloads.onCreated.addListener(async (delta) => {
  let status = await getEnableStatus()
  if (status != true) {
      console.log("DDR download tracking function is not yet enabled")
      return
  }
  await getCurrentPage(delta.id)
});

chrome.downloads.onChanged.addListener(async (delta) => {

  if (!delta.state || delta.state.current !== "complete") {
    return;
  }
  chrome.downloads.search({ id: delta.id }, async (results) => {
    if (results.length > 0) {
      
      //Since the downloads are handled by the agent to calculate the file hash, there is no need to determine the file size
      //const fileSizeInGB = results[0].fileSize / (1024 * 1024 * 1024);
      let status = await getEnableStatus()
      if (status != true) {
          console.log("DDR download tracking function is not yet enabled")
          return
      }
      await collateDownloadData(results)

    }
  });
});

////////////////////
//  Upload Block  // 
////////////////////

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  // console.log("listen: ", message)
  if (message.hash) {
    // console.log("Upload file hash: ", message.hash, message.fileName)
    // Handle async without returning Promise to avoid blocking other listeners
    (async () => {
      await getCurrentPage(message.hash)
      await collateUploadData(message.fileName, message.hash)
    })();
  }
  // Don't return anything - let other listeners handle their messages
});

///////////////////////
// Clean DDR Storage // 
///////////////////////

function cleanUpCache() {
  chrome.storage.local.get(null, (items) => {
    const now = Date.now();
    const keysToRemove = [];

    for (const key in items) {
      // console.log("item: ", items[key])
      // console.log("key: ", key)
      if (Array.isArray(items[key]) && items[key].length == 4 && items[key][3] < now) {
        keysToRemove.push(key);  // Remove both the data and the expiry key
      }
    }

    // Remove expired keys
    if (keysToRemove.length > 0) {
      chrome.storage.local.remove(keysToRemove, () => {
        console.log("Removed expired cache items:", keysToRemove);
      });
    }
  });
}

////////////////////
// WTP Block // 
////////////////////

// Listener of content.js or wtp.js
chrome.runtime.onMessage.addListener(
  function (request, sender, sendResponse) {
    var uniqueId = generateRamdomNumber();
    sendResponseMap.set(uniqueId, sendResponse);
    /* //remove dlp
    if (request.type == "networkData") {
      uniqueIdMap.set(uniqueId, request.extId);
      expireMap.set(uniqueId, new Date().getTime() + expireInterval);
      var message = {
        id: uniqueId,
        type: request.type,
        params: request.params,
        date: generateTimeString()
      };
      sendNativeMessage(message);
      return true; 
    }else*/

    if (request.type == "wtpData") {
      console.log("[addListener]uniqueId is: " + uniqueId);
      console.log("[addListener]mapSize is " + sendResponseMap.size);
      var message = {
        id: uniqueId,
        type: request.type,
        params: request.params,
        date: generateTimeString()
      };
      sendNativeMessage(message);
      return true;
    }
  });

chrome.alarms.create("SwStartAlarm", { delayInMinutes: 1 });
chrome.alarms.onAlarm.addListener(async (alarm) => {
  console.log("[onAlarm]Start " + alarm);
  var ptLog = "Service worker start. mapSize: " + mapSizeValue;
  var ptParams = {}
  ptParams[mapSizeKey] = mapSizeValue;
  await collectWtpPtInfo(0, ptParams, ptLog);
  console.log("[onAlarm]End. wtpMessage is " + ptLog);
})

////////////////////
//// Interval ///// 
////////////////////
// Periodically run the cache cleanup (e.g., every 10 minutes)
setInterval(cleanUpCache, CACHE_DURATION_IN_MS);  // 10 minutes

export var sendResponseMap = new Map();
export var mapSizeKey = "mapSize";
