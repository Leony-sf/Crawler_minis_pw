/*************************************************************************
* ADOBE CONFIDENTIAL
* ___________________
*
*  Copyright 2015 Adobe Systems Incorporated
*  All Rights Reserved.
*
* NOTICE:  All information contained herein is, and remains
* the property of Adobe Systems Incorporated and its suppliers,
* if any.  The intellectual and technical concepts contained
* herein are proprietary to Adobe Systems Incorporated and its
* suppliers and are protected by all applicable intellectual property laws,
* including trade secret and or copyright laws.
* Dissemination of this information or reproduction of this material
* is strictly forbidden unless prior written permission is obtained
* from Adobe Systems Incorporated.
**************************************************************************/
import{common as o}from"./common.js";import{dcLocalStorage as e}from"../common/local-storage.js";let n;class a{constructor(){this.LOG=(...e)=>o.LOG(...e)}createLink=async function({ios_deeplink_path:o,android_deeplink_path:n,fallback_url:a,session_id:r,web_only:t=!1}={}){const i=await fetch("https://api2.branch.io/v1/url",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({branch_key:"key_live_flDW3W4eHDwFJI2KlQ04gmjpvEcHGeEc",alias:crypto.randomUUID(),data:{$ios_deeplink_path:o,$android_deeplink_path:n,$fallback_url:a,...t&&{$web_only:!0},landing_screen:"capture",capture_type:"document",workflow:"scan_web_extension_upload",will_show_confirmation_dialog:!e?.getItem("magicScanConfirmSkip"),session_id:r},type:1})});if(!i.ok)throw new Error(`branch/url failed: ${i.status}`);const{url:l}=await i.json();if(!l)throw new Error("branch/url response missing url field");return l}}n||(n=new a);export const branchModule=n;