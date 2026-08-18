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
import{floodgate as e}from"./floodgate.js";import{checkUserLocaleEnabled as o,safeParseFeatureFlag as s}from"./gsuite/util.js";import{util as t}from"./util.js";async function i(i){const[a,n]=await Promise.all([e.hasFlag("dc-cv-gmail-message-view-compress-pdf-touch-point"),e.hasFlag("dc-cv-gmail-message-view-compress-pdf-touch-point-control")]);let c;a?c=s("dc-cv-gmail-message-view-compress-pdf-touch-point"):n&&(c=s("dc-cv-gmail-message-view-compress-pdf-touch-point-control"));const l=o(c?.enLocaleEnabled,c?.nonEnLocaleEnabled),r=c?.messageViewSelectors||{},m=c?.tooltip||{},p=c?.fteEnabled||!1,g=!t.isAcrobatTouchPointEnabled("acrobat-touch-point-in-gmail");i({enableGmailMessageViewCompressPDFTouchPoint:a&&!g&&l,messageViewSelectors:r,compressPDFSizeThreshold:c?.compressPDFSizeThreshold||0,compressPDFString:t.getTranslation("gmailCompressPDFTouchPoint"),fteToolTipStrings:{title:t.getTranslation("gmailCompressPDFTouchPointFTEHeader"),description:t.getTranslation("gmailMessageViewCompressPDFTouchPointFteDescription"),button:t.getTranslation("closeButton")},enableFte:p,fteConfig:m})}export{i as gmailMessageViewCompressPDFInit};