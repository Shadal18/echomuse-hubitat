/* EchoMuse Speaker v0.5.0 - child driver for EchoMuse Bridge */
metadata {
    definition(name: "EchoMuse Speaker", namespace: "echomuse.community",
               author: "EchoMuse Hubitat Community") {
        capability "SpeechSynthesis"
        capability "Notification"
        capability "Refresh"
        attribute "announcementStatus", "string"
        attribute "lastAnnouncementError", "string"
        attribute "lastRequestId", "string"
        attribute "bridgeStatus", "string"
        command "testAnnouncement"
    }
}

void installed() {
    setBridgeStatus("unknown")
    setAnnouncementState("idle", "", "")
}

void updated() { }

void speak(String text, Number volume = null, String voice = null) {
    if (volume != null || voice) {
        log.warn "EchoMuse currently uses the configured Piper voice and existing playback volume; per-message overrides are ignored."
    }
    if (!parent) {
        setAnnouncementState("rejected", "Install through the EchoMuse Bridge app", "")
        return
    }
    parent.sendSpeakerAnnouncement(device.deviceNetworkId, text)
}

void deviceNotification(String text) { speak(text) }

void refresh() {
    if (parent) parent.refreshSpeaker(device.deviceNetworkId)
    else setBridgeStatus("notConfigured")
}

void testAnnouncement() {
    speak("This is a test announcement from Hubitat.")
}

void setAnnouncementState(String status, String error, String requestId) {
    sendEvent(name: "announcementStatus", value: status)
    sendEvent(name: "lastAnnouncementError", value: error ?: "none")
    sendEvent(name: "lastRequestId", value: requestId ?: "none")
}

void setBridgeStatus(String status) {
    sendEvent(name: "bridgeStatus", value: status)
}
