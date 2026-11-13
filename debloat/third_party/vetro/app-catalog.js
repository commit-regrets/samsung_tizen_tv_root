'use strict';
// What each package does and whether a home TV needs it. Areas and roles are
// Vetro's assessment from the Q80A firmware manifests (app-facts.js) and device
// tests; they are guidance, not a guarantee for other models or firmware.
var facts = require('./app-facts.js');

var AREAS = {
    tracking: 'Advertising and tracking',
    voice: 'Voice assistants',
    tv: 'TV and channels',
    home: 'Home and menus',
    media: 'Apps and media',
    ambient: 'Ambient and art',
    sharing: 'Multi View and mirroring',
    devices: 'Bluetooth and devices',
    samsung: 'Samsung account and SmartThings',
    support: 'Diagnostics and support',
    commercial: 'Hotel, shop and factory',
    system: 'System services'
};
// keep: the TV relies on it. optional: a feature you may not use.
// tracking: collects viewing or advertising data. unused: commercial modes only.
var ROLES = {
    keep: 'Keep',
    optional: 'Optional',
    tracking: 'Tracking',
    unused: 'Not used at home'
};
var AREA_ROLE = {tracking: 'tracking', voice: 'optional', tv: 'keep', home: 'keep', media: 'optional', ambient: 'optional',
    sharing: 'optional', devices: 'optional', samsung: 'optional', support: 'optional', commercial: 'unused', system: 'keep'};

// Ordered: the first matching rule wins. Patterns match the package ID.
var RULES = [
    ['system', /^vetrotvapp/],
    ['tracking', /acr-service|^com\.samsung\.tv\.acr$|canalysis|^com\.samsung\.tv\.iacr$|screen-analysis|contents-recognition|nvision-analysis|vision-data-recognition|targeted-ad|ad-web-framework|^adplatform$|adplayer|samsung-analytics|cis-service-app|cis-api-service-app|coba\.adagent|pisa-service|privacy_app|PrivacyChoices|tv6pbVMQFF|content-grab-service|contents-ott-detector|contents-ui-detector/],
    ['voice', /alexa|bixby|google-assistant|wakeup-engine|voice|vif$|farfieldvoice|aov-|cnvoice|utterance-recommender|action-planner|fuzzy-search-engine|intelligent-action|stt-|tts-engine|multi-assistant/],
    ['commercial', /^com\.samsung\.ep[.-]|ep-hotel|ephotel|ep-boot|ep-event|ep-system|^ep-|hotel|factory|AgingApp|cloning|demo-player|remote-shop-care|UsbSyncDisplay|plateau|automation-(alert|app|viewer)|widget_viewer_sdk|hitcomp|remote-service-logging/],
    ['support', /TVDeviceCare|easy-support|remote-management|request-support|smarthub-connection-test|picture-test|sound-test|video-test|hdmi-troubleshooting|built-in-app-info-viewer|RunningApps|remoteguide|emanual|LzU5yAFXeg/],
    ['ambient', /ambient|coba\.(art|clock|decor|photo|poster|cinemagraph|specialedition|edenview|msview|aodview)$|art-app|-tpl$|cinemagraph|portlandclock|music-flex|bouroullec|weather-viewer|\.aod$|contentimageapp/],
    ['sharing', /coba\.mv|multiview|multiscreen|ScreenMirroring|p2p-asm|airplay|NRi6kdBYJ0|soundmirroring|mobilebff|remoteworkspace|coss|csfw\.provider|SMSourceAPP|5-way-function|remote-workspace|remotepc|remoteapp|knox-browser-autofill|camera-launcher|XPkceUl3N4|coba\.usbcam/],
    ['devices', /\bbt|btapp|btaudio|bmplayer|NetworkSpeaker|hdmicec|SmartRC|mbr-|registerav|register-device|registertv|connection-guide|easysetup|aispeaker|nfc-|av-sync|waapp|aisound|aitech-app|wifi-motion|ocf-d2d|samsunghealth/],
    ['samsung', /samsung-(account|cloud|pass-agent|service-manager)|smartthings|content-continuity|content-panel|autofill|\.sso|ssoservice|sso-menu|CSAccount|CSBilling|billing-helper|account-extra|cms-service|WykOS4t4F0|ZODRT12q2l|csft-service|coba\.samsungaccount|iot-service|digitalbutler|mde-framework|vd-sc-client|heremaps|provider-resetpsid|csa$/],
    ['tv', /tv-viewer|channel|epg|pvr|ci-app|nagsam|hbbtv|ttxUG|antenna|autosetup-channel|stand-by-scan|reminder|schedule-manager|tv-scheduler|tvplus|tvPlusDeeplinker|w2VwCK465D|slive|broadcastingmenu|coba\.livetv|coba\.source|aoc-enabler|preview-downloader|tvkey-preview|rct-|AVControl/],
    ['home', /coba\.(home|apps|search|setting|dhcategory|remoteguide|smartthings|soundmirroring|home-notification)|csfs|org\.tizen\.menu$|function-osd|quickpanel|searchall|\.store$|notification|wizard|homesetting|swu-ui|smarthub-reset|alert-syspopup|volume-setting|shortcut|gamebar|welcome-mode|tvlaunch|graphiczoom|screen-reader|sboard-app/],
    ['media', /ContentsBrowser|cobalt|netflix|primevideo|aria-video|30IKH0OX8U|lib-ariafw|browser|gallery|mycontent|photo-player|video-player|usb-launcher|ghdaemon|ghservice|pvod|^[A-Za-z0-9]{10}$/]
];

// Purpose in plain words where the manifest description is missing or unclear.
var PURPOSE = {
    'com.samsung.tv.acr-service-app': 'Automatic content recognition: identifies what is on screen and reports viewing data.',
    'com.samsung.tv.canalysis-service': 'Content analysis daemon used by viewing-information services.',
    'com.samsung.tv.contents-recognition-dbmgr': 'Database for on-screen content recognition.',
    'com.samsung.tv.nvision-analysis-dbmgr': 'Model manager for on-screen image analysis.',
    'com.samsung.tv.vision-data-recognition-service': 'Recognises on-screen visual data for viewing analytics.',
    'com.samsung.tv.cis-service-app': 'Content information service that feeds ACR.',
    'com.samsung.tv.cis-api-service-app': 'API service for content information (ACR).',
    'com.samsung.tv.targeted-ad-service': 'Selects targeted advertising.',
    'com.samsung.tv.ad-web-framework': 'Shows web-based advertising, for example in Samsung TV Plus.',
    'adplatform': 'Advertising player.',
    'com.samsung.tv.adplayer': 'Advertising player.',
    'com.samsung.tizen.samsung-analytics': 'Collects and uploads Samsung usage analytics.',
    'com.samsung.tv.coba.adagent': 'Smart Hub advertising agent. Home loads part of it, so Vetro protects it.',
    'com.samsung.tv.pisa-service': 'Personalised content and advertising service for Smart Hub.',
    'com.samsung.tv.coba.privacy_app': 'Privacy choices screen.',
    'tv6pbVMQFF': 'Privacy choices web app.',
    'content-grab-service': 'Captures frames of the current picture for content services.',
    'org.tizen.multi-assistant-service': 'Hub that switches between voice assistants and handles the microphone.',
    'com.samsung.tv.action-planner-service': 'Turns voice requests into TV actions.',
    'com.samsung.tv.aov-service': 'Always-on voice: listens for wake words.',
    'org.tizen.tts-engine-vd-DVB': 'Text-to-speech used by Voice Guide (accessibility).',
    'org.tizen.voice-onboarding': 'First-run setup for voice assistants.',
    'org.tizen.tv-viewer': 'Live TV picture and source playback. Required.',
    'org.tizen.menu': 'TV settings menu. Required.',
    'com.samsung.tv.csfs': 'Home screen (First Screen). Required.',
    'com.samsung.tv.store': 'Samsung app store.',
    'com.samsung.tv.swu-ui': 'Software update screens.',
    'org.tizen.function-osd': 'On-screen controls for TV functions.',
    'com.samsung.tv.searchall': 'Universal search.',
    'org.tizen.wizard': 'First-time setup.',
    'comss': 'Content service host used by many Smart Hub services. Required.',
    'org.tizen.chromium-efl': 'Web engine for web apps and the browser. Required.',
    'com.samsung.tv.cobalt': 'YouTube and other Cobalt-based apps.',
    'com.samsung.tv.mde-framework': 'Multi-device experience framework (SmartThings, phone links).',
    'com.samsung.tv.digitalbutler-app': 'Discovers and controls nearby devices (Digital Butler).',
    'com.samsung.tizen.smartthings-client': 'SmartThings client.',
    'com.samsung.tizen.samsung-service-manager': 'Coordinates Samsung account, cloud and SmartThings services.',
    'org.tizen.ScreenMirroring-app-tv': 'Smart View screen mirroring.',
    'com.samsung.tv.airplay-app': 'Apple AirPlay receiver.',
    'org.tizen.ssoservice': 'Samsung account sign-in service.',
    'com.samsung.TVDeviceCare': 'Device Care: diagnostics and cleanup screens.',
    'samsung-easy-support': 'Remote support tool for Samsung service centres.',
    'org.tizen.remote-management': 'Remote management for Samsung support.',
    'org.tizen.factory': 'Factory service menu.',
    'org.tizen.provider-resetpsid': 'Resets the advertising identifier (PSID) from the privacy menu.',
    'com.samsung.tv.ContentsBrowser': 'Universal Guide: content recommendations from streaming services.',
    'capi-bnr-tv': 'Backup and restore of settings for automatic setup.',
    'vetrotvapp': 'Vetro. Protected.'
};

function areaOf(packageId, appId) {
    var ids = [packageId || '', appId || ''];
    for (var i = 0; i < RULES.length; i++) {
        if (ids.some(function (id) { return RULES[i][1].test(id); })) return RULES[i][0];
    }
    return 'system';
}

function describe(row) {
    var pkg = row.packageId || row.appId, fact = facts.packages[pkg] || null;
    var area = areaOf(pkg, row.appId);
    var role = AREA_ROLE[area];
    if (/^vetrotvapp/.test(pkg) || pkg === 'com.samsung.tv.coba.adagent') role = 'keep';
    if (area === 'media' && row.origin === 'installed') role = 'optional';
    var purpose = PURPOSE[row.appId] || PURPOSE[pkg] || (fact && fact.description) || null;
    return {
        area: area, areaLabel: AREAS[area], role: role, roleLabel: ROLES[role], purpose: purpose,
        referencedBy: fact ? fact.usedBy : null, startsOn: fact && fact.startsOn || [], access: fact && fact.access || [],
        source: fact ? 'firmware manifest' : 'name rules'
    };
}

module.exports = {AREAS: AREAS, ROLES: ROLES, RULES: RULES, areaOf: areaOf, describe: describe, source: facts.source};
