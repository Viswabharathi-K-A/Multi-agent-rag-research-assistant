
"use strict";

const chatForm = document.getElementById("chat-form");
const sendButton = document.getElementById("send-button");

chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
});

// The send button remains disabled until the real
// SSE endpoint is integrated. No mock response is used.
sendButton.disabled = true;
