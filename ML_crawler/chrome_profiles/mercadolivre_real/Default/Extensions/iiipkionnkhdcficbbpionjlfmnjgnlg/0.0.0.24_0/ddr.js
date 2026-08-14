const CACHE_DURATION_IN_MS = 600000; // 10 minute (adjust as needed)

async function generateSHA1HashFromFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
  
      // Load the file's contents as an ArrayBuffer
      reader.onload = async function(event) {
        const fileArrayBuffer = event.target.result;
        try {
          // Generate the SHA-1 hash of the file's content
          const hashBuffer = await window.crypto.subtle.digest("SHA-1", fileArrayBuffer);
          // Convert the ArrayBuffer to a hexadecimal string
          const hashArray = Array.from(new Uint8Array(hashBuffer));
          const hashHex = hashArray.map(b => b.toString(16).padStart(2, "0")).join("");
  
          resolve(hashHex);
        } catch (error) {
          reject(error);
        }
      };
  
      // Handle file read error
      reader.onerror = function() {
        reject(new Error("Error reading the file."));
      };
  
      // Read the file as an ArrayBuffer
      reader.readAsArrayBuffer(file);
    });
  }

// file handler function
async function handleFiles(files) {
    const maxFileSize = 2 * 1024 * 1024 * 1024; // 2GB in bytes

    for (let i = 0; i < files.length; i++) {
        let file = files[i];

        if (file.size > maxFileSize) {
            console.warn(`Upload File ${file.name} exceeds 2GB and will not be processed.`);
            continue; // Skip this file
        }

        let hashHex = await generateSHA1HashFromFile(file)
        chrome.runtime.sendMessage({fileName: file.name, hash: hashHex.toString()});
    }
}

// listener of file upload change
document.addEventListener('change', async function (event) {
    try{
        const change_files = event.target.files;
        let status = await getEnableStatus()
        if (status != true) {
            await ddrDebug("DDR upload tracking function is not yet enabled");
            return
        } 
        await ddrDebug("DDR upload tracking function is enabled");
        if (event.target.type === 'file') {
            await handleFiles(change_files);
        }
    } catch (err) {
        console.warn("DDR file event handler error:", err);
    }
}, true);

// listener of file upload drop event
// document.addEventListener("drop", async function (event) {
//     try{
//         const drop_files = event.dataTransfer.files;
//         if (!drop_files || drop_files.length === 0) return;
//         if (drop_files) {
//             await handleFiles(drop_files)
//         }
//     } catch (err) {
//         console.warn("DDR drop handler error:", err);
//     }
// });

function waitForElement(selector, callback) {
    const observer = new MutationObserver((mutations, obs) => {
        const element = document.querySelector(selector);
        if (element) {
            obs.disconnect();
            callback(element);
        }
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    const element = document.querySelector(selector);
    if (element) {
        observer.disconnect();
        callback(element);
    }
}

// listener of file upload drop event in google drive
waitForElement('.v9czFf', (googleUploadDraw) => {
    googleUploadDraw.addEventListener('drop', async (event) => {
            try{
                const drop_files = event.dataTransfer.files;
                let status = await getEnableStatus()
                if (status != true) {
                    await ddrDebug("DDR upload tracking function is not yet enabled");
                    return
                }
                await ddrDebug("DDR upload tracking function is enabled");
                if (drop_files) {
                    await handleFiles(drop_files)
                }
            } catch (err) {
                console.warn("DDR file event handler error:", err);
            }
    });
});

// listener of file upload drop event in onedrive
waitForElement('.with-breadcrumb', (oneDriveUploadDraw) => {
    oneDriveUploadDraw.addEventListener('drop', async (event) => {
            try{
                const drop_files = event.dataTransfer.files;
                let status = await getEnableStatus()
                if (status != true) {
                    await ddrDebug("DDR upload tracking function is not yet enabled");
                    return
                }
                await ddrDebug("DDR upload tracking function is enabled");
                if (drop_files) {
                    await handleFiles(drop_files)
                }
            } catch (err) {
                console.warn("DDR file event handler error:", err);
            }
    });
});

function onElementAdded(selector, callback) {
    document.querySelectorAll(selector).forEach(el => callback(el));
    const observer = new MutationObserver((mutations) => {
        mutations.forEach(mutation => {
            mutation.addedNodes.forEach(node => {
                if (!(node instanceof HTMLElement)) return;
                if (node.matches && node.matches(selector)) {
                    callback(node);
                }
                node.querySelectorAll && node.querySelectorAll(selector).forEach(el => callback(el));
            });
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
}

const dropSelectors = [
    '.maestro-app', // listener of file upload drop event in dropbox
    '._outlineOuter_hybei_1', // listener of file upload drop event in dropbox
    '.em_N.D_F.ek_BB.p_R.o_h' // listener of file upload drop event in yahoo mail
];

dropSelectors.forEach(selector => {
    onElementAdded(selector, (uploadDraw) => {
        // Avoid adding duplicate event listeners
        if (uploadDraw._ddrDropHandlerAdded) return;
        uploadDraw._ddrDropHandlerAdded = true;

        uploadDraw.addEventListener('drop', async (event) => {
            try{
                const drop_files = event.dataTransfer.files;
                let status = await getEnableStatus()
                if (status != true) {
                    await ddrDebug("DDR upload tracking function is not yet enabled");
                    return
                }
                await ddrDebug("DDR upload tracking function is enabled");
                if (drop_files) {
                    await handleFiles(drop_files)
                }
            } catch (err) {
                console.warn("DDR file event handler error:", err);
            }
        });
    });
});

function getQueryParam(url, param) {
    let params = new URL(url).searchParams;
    return params.get(param);
}

function getUrlPath(url) {
    let urlObj = new URL(url);
    return decodeURIComponent(urlObj.pathname);
}

function hasUrl(url, prefix) {
    return url.includes(prefix);
}

function getCloudFilePath(url) {
    const google = hasUrl(url, 'drive.google.com'); 
    const oneDrive = hasUrl(url, 'sharepoint')
    const dropbox = hasUrl(url, 'dropbox')
    const gmail = hasUrl(url, 'mail.google.com')
    const yahoo = hasUrl(url, 'yahoo')
    const outlook = hasUrl(url, 'outlook.office.com')
    full_path = ""
    provider = ""
    if (google) {
        const googleDom = document.querySelector('.o-Yc-Wb'); 
        if(googleDom){
            Array.from(googleDom.children).forEach(function(child) {
                if (child.tagName.toLowerCase() === 'div') { 
                    text = child.textContent.trim();
                    if (text == "") {
                        full_path += "...";
                    } else {
                        full_path += text
                    }
                    full_path += "/"
                }
            });
        }
        provider = "googledrive"
    } else if (oneDrive) {
        full_path = getQueryParam(url, 'id')
        provider = "onedrive"
    } else if (dropbox) {
        full_path = getUrlPath(url)
        provider = "dropbox"
    } else if (gmail) {
        provider = "gmail"
    } else if (yahoo) {
        provider = "yahoo"
    } else if (outlook) {
        provider = "outlook"
    }
    return [full_path, provider]
}

function getAccountUser(url) {
    try {
        let googleAccount;
        let dropboxAccount;
        let oneDriveAccount;
        if (hasUrl(url, 'drive.google.com')) {
            googleAccount = document.querySelector('.gb_B.gb_Za.gb_0');
        }
        if (hasUrl(url, 'dropbox')) {
            let dropbox_script = document.querySelectorAll('script');
            dropboxAccount = ""
            dropbox_script.forEach((script) => {
                if (script.innerText.includes('edisonModule.Edison.registerStreamedDataModule')) {
                    let jsonMatch = script.innerText.match(/"json",\s*("(?:\\.|[^"\\])*")/);
                    if (jsonMatch) {
                        let jsonStr = JSON.parse(jsonMatch[1]);
                        let jsonData = JSON.parse(jsonStr);
                        dropboxAccount = jsonData?._viewer_properties?._user_data?.[0]?.email;
                    }
                }
            });
        }
        if (hasUrl(url, 'sharepoint')) {
            oneDriveAccount = document.getElementById("O365_MainLink_Me")
        }
    
        if (googleAccount) {
            return googleAccount.ariaLabel
        } else if (oneDriveAccount) {
            return oneDriveAccount.textContent
        } else if (dropboxAccount != "") {
            return dropboxAccount
        }
    
        return ""
    } catch (e){
        console.warn("parser account error: "+e)
        return ""
    }
}

async function getEnableStatus() {
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

// Get debug mode status
async function getDebugMode() {
    return await new Promise((resolve) => {
        chrome.storage.local.get(["isDebugMode"], function (result) {
            resolve(result["isDebugMode"] === true);
        });
    });
}

async function ddrDebug(msg, ...args) {
    if (await getDebugMode()) {
        console.log(msg, ...args);
    }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === "GET_PAGE_DATA") {
        let key = message.id
        let url = message.url
        let pathAndProvider = getCloudFilePath(url);
        let accountUser = getAccountUser(url)

        pathAndProvider.push(accountUser)

        // setup expired time
        const expiryTime = Date.now() + CACHE_DURATION_IN_MS;

        pathAndProvider.push(expiryTime)

        // setup Browser url
        pathAndProvider.push(decodeURIComponent(url))

        chrome.storage.local.set({ 
            [key]: pathAndProvider
        }, function() {
            (async () => {
                await ddrDebug('Click data saved to storage.');
            })();
        });
        sendResponse({ status: "OK" });
    }
});