import { generateRamdomNumber, generateTimestamp, sendNativeMessage } from './utils.js';

////////////////////
//   Util Block   // 
////////////////////

// async function getFileHash(fileUrl) {
//     try {
//         const response = await fetch(fileUrl)
//         const arrayBuffer = await response.arrayBuffer();
//         const hash = await generateSHA1(arrayBuffer);
//         return hash
//     } catch (e) {
//         console.log("download hash fail: ", e)
//     }
//     return ""
// }

// // SHA-1 Function
// async function generateSHA1(arrayBuffer) {
//     const hashBuffer = await crypto.subtle.digest('SHA-1', arrayBuffer);
//     return arrayBufferToHex(hashBuffer);
// }

// // Change ArrayBuffer to Hex
// function arrayBufferToHex(buffer) {
//     const view = new DataView(buffer);
//     let hex = '';
//     for (let i = 0; i < view.byteLength; i += 4) {
//         const value = view.getUint32(i);
//         hex += ('0000000' + value.toString(16)).slice(-8);
//     }
//     return hex;
// }

// get user info
async function getChromeUser() {
    // Fetch user profile information
    const email = await new Promise((resolve, reject) => {
        chrome.identity.getProfileUserInfo(function (userInfo) {
            if (chrome.runtime.lastError) {
                console.error(chrome.runtime.lastError.message);
                return reject(chrome.runtime.lastError.message);
            }
            resolve(userInfo.email);
        });
    });
    return email
}

async function getStroageInfo(storage_id) {
    const path = await new Promise((resolve, reject) => {
        chrome.storage.local.get([storage_id.toString()], function (result) {
            if (chrome.runtime.lastError) {
                reject(chrome.runtime.lastError.message);
            } else {
                resolve(result[storage_id.toString()]);
            }
        });
    });

    await new Promise((resolve, reject) => {
        chrome.storage.local.remove([storage_id.toString()], function () {
            if (chrome.runtime.lastError) {
                reject(chrome.runtime.lastError.message);
            } else {
                console.log(`${storage_id} has been removed from local storage.`);
                resolve();
            }
        });
    });

    return path;
}

export async function getCurrentPage(keyId) {
    try {
        // Wrap chrome.tabs.query in a promise
        const tabs = await new Promise((resolve, reject) => {
            chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
                if (tabs.length > 0) {
                    resolve(tabs);
                } else {
                    reject("No active tab found.");
                }
            });
        });

        const activeTabId = tabs[0].id;
        const tabURL = tabs[0].url;

        // Wrap chrome.tabs.sendMessage in a promise
        const response = await new Promise((resolve) => {
            chrome.tabs.sendMessage(activeTabId, { type: "GET_PAGE_DATA", id: keyId, url: tabURL }, (response) => {
                resolve(response);
            });
        });

        if (response && response.status) {
            console.log("DOM catch success");
        } else {
            console.log("DOM catch failed");
        }
    } catch (error) {
        console.error(error);
    }
}

function ensureNonEmptyValues(obj) {
    for (const key in obj) {
        if (obj[key] === null || obj[key] === undefined) {
            obj[key] = "";
        }
    }
    return obj;
}

export async function collateDownloadData(rawData) {
    var uniqueId = generateRamdomNumber();
    // let hash = await getFileHash(rawData[0].url)
    let storageInfo = await getStroageInfo(rawData[0].id)
    var dataInfo = {
        FileHash: "",
        BrowserType: "chrome",
        Type: "download",
        URI: storageInfo[4],
        BrowserUser: await getChromeUser(),
        User: storageInfo[2],
        Provider: storageInfo[1],
        From: storageInfo[0],
        To: rawData[0].filename,
        Timestamp: generateTimestamp()
    };
    // Ensure non-empty values
    dataInfo = ensureNonEmptyValues(dataInfo);
    var message = {
        id: uniqueId,
        type: "ddrData",
        params: dataInfo
    };
    console.log("Download Info: ", message)
    await sendNativeMessage(message);
}

export async function collateUploadData(fileName, hash) {
    var uniqueId = generateRamdomNumber();
    let storageInfo = await getStroageInfo(hash)
    var dataInfo = {
        FileHash: hash,
        BrowserType: "chrome",
        Type: "upload",
        URI: storageInfo[4],
        BrowserUser: await getChromeUser(),
        User: storageInfo[2],
        Provider: storageInfo[1],
        From: ".../" + fileName,
        To: storageInfo[0],
        Timestamp: generateTimestamp()
    };
    // Ensure non-empty values
    dataInfo = ensureNonEmptyValues(dataInfo);
    var message = {
        id: uniqueId,
        type: "ddrData",
        params: dataInfo
    };
    console.log("Upload Info: ", message)
    await sendNativeMessage(message);
}
