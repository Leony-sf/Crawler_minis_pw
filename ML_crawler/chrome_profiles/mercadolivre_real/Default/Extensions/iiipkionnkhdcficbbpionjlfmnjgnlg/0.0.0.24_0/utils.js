import { sendResponseMap, mapSizeKey } from './background.js';
import { collectWtpPtInfo } from './wtp_bg.js';

var port = null;
var swKey = "SwData"

async function ensurePortConnectNative() {
    if (port == null) {
        const hostName = "com.trendmicro.chrome.dlp";
        console.log("Connecting to native messaging host " + hostName);

        port = await new Promise((resolve, reject) => {
            const nativePort = chrome.runtime.connectNative(hostName);

            nativePort.onMessage.addListener(onNativeMessage);
            nativePort.onDisconnect.addListener(onDisconnected);

            // Resolve the promise with the port when the connection is established
            resolve(nativePort);
        });
    }
}

// Send to native app
export async function sendNativeMessage(message) {
    await ensurePortConnectNative();
    console.log("Message sent to native app: ", message);
    port.postMessage(message);
}

export function generateRamdomNumber() {
    var uniqueId = parseInt(Math.random() * 100000000, 10);
    /*     //remove dlp
    while (uniqueIdMap.has(uniqueId)) {
      uniqueId = generateRamdomNumber();
    }*/
    return uniqueId;
}

export function generateTimeString() {
    var date = new Date();
    return date.getFullYear().toString() + "/" + date.getMonth().toString() + "/" + date.getDate().toString() + " " + date.getHours().toString() + ":" + date.getMinutes().toString() + ":" + date.getSeconds().toString() + "." + date.getMilliseconds().toString();
}

export function generateTimestamp() {
    return new Date().getTime().toString();
}

// Listener of native app
async function onNativeMessage(message) {
    console.log("Message type is :" + message.type);
    /* // remove dlp
    if (message.type == "networkData") {
      console.log("[networkData]Message sent back to extension: ", message);
      var uniqueId = parseInt(message.id);
      var id = uniqueIdMap.get(uniqueId);
      if(id) {
        var sendResponse = sendResponseMap.get(uniqueId);
        sendResponse({id: uniqueId, params: {xhrAllowed: message.params.allowed}, extId: id});
        message.date = generateTimeString();
        uniqueIdMap.delete(uniqueId);
        sendResponseMap.delete(uniqueId);
        expireMap.delete(uniqueId);
      }  
    }else */

    if (message.type == "wtpData") {

        var uniqueId = parseInt(message.id);
        console.log("[onNativeMessage]wtpData: uniqueId is " + uniqueId);
        console.log("[onNatvieMessage mapSize is " + sendResponseMap.size);
        var sendResponse = sendResponseMap.get(uniqueId);
        if (sendResponse == undefined) {
            var errStr = "[onNativeMessage] Not Exist. UniqueId: " + toString(uniqueId) + ", mapSize: " + toString(sendResponseMap.size);
            var ptParams = {}
            ptParams[mapSizeKey] = sendResponseMap.size;
            await collectWtpPtInfo(uniqueId, ptParams, errStr);
        } else {
            //sendResponse({id: uniqueId, params: {xhrAllowed: message.params.allowed}, extId: id});
            if (message.isBlock) {
                console.log('[onNativeMessage]block!');
                var msg = { databc: message.block_data };
                console.log("[wtpData]Message sent back to content js: ", msg);
                sendResponse(msg);
            }
            sendResponseMap.delete(uniqueId);
        }

        //store map size
        chrome.storage.local.set({ [swKey]: { [mapSizeKey]: sendResponseMap.size } });

        /* //remove dlp
        message.date = generateTimeString();
        uniqueIdMap.delete(uniqueId);
        //sendResponseMap.delete(uniqueId);
        expireMap.delete(uniqueId);*/
    }

    if (message.type == "browserData") {
        // console.log("message: "+JSON.stringify(message))
        if (message.enable == true) {
            chrome.storage.local.set({ enable: true }, () => {
                console.log("Enable Browser Feature Setting.");
            });
        } else if (message.enable == false) {
            chrome.storage.local.set({ enable: false }, () => {
                console.log("Disable Browser Feature Setting.");
            });
        } else {
            console.error("Unable to parse the status of browser", message)
        }
    }
}

function onDisconnected() {
    if (chrome.runtime.lastError != null) {
        console.log("Failed to connect: " + chrome.runtime.lastError.message);
    }
    port = null;
}

export async function getEnableStatus() {
    let status = false
    status = await new Promise((resolve, reject) => {
        chrome.storage.local.get(["enable"], function (result) {
            if (chrome.runtime.lastError) {
                reject(chrome.runtime.lastError.message);
            } else {
                resolve(result["enable"]);
            }
        });
    });
    return status
}
