document.addEventListener("DOMContentLoaded", function () {
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const chatMessages = document.getElementById("chat-messages");
    const maxRetries = 15;
    const processingTimeout = 30000; // 30 seconds timeout for processing messages
    let retryCount = 0;
    let lastMessageId = 0;
    let waitingMessageIds = new Set(); // Track messages we're waiting for
    const refreshInterval = 2000; // 2 seconds for frequent updates
    let refreshTimer;
    const urlParams = new URLSearchParams(window.location.search);
    const conversationId = urlParams.get('conversation_id') ? parseInt(urlParams.get('conversation_id'), 10) : null;
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function formatTimestamp(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleString();
    }

    function createMessageElement(message) {
        const messageElement = document.createElement("div");
        messageElement.classList.add("message", message.direction === "IN" ? "user" : "bot");
        messageElement.setAttribute("data-id", message.id);
        
        const contentSpan = document.createElement("span");
        contentSpan.classList.add("message-content");
        contentSpan.textContent = message.content;
        messageElement.appendChild(contentSpan);

        const timeElement = document.createElement("small");
        timeElement.classList.add("message-time");
        timeElement.textContent = formatTimestamp(message.timestamp);
        messageElement.appendChild(timeElement);

        if (message.direction === "OUT" && message.content === "Procesando respuesta...") {
            messageElement.classList.add("waiting");
            
            // Add timestamp for timeout tracking
            messageElement.setAttribute("data-waiting-since", new Date().getTime());
            waitingMessageIds.add(message.id);
        }

        return messageElement;
    }

    function updateExistingMessage(existingMessage, newMessage) {
        const contentSpan = existingMessage.querySelector('.message-content');
        if (contentSpan) {
            contentSpan.textContent = newMessage.content;
        }
        existingMessage.classList.remove("waiting");
        
        const timeElement = existingMessage.querySelector('.message-time');
        if (timeElement) {
            timeElement.textContent = formatTimestamp(newMessage.timestamp);
        }
        
        // Remove from waiting list if it was waiting
        if (waitingMessageIds.has(newMessage.id)) {
            waitingMessageIds.delete(newMessage.id);
        }
    }

    function checkForTimeouts() {
        // Check all waiting messages for timeout
        const now = new Date().getTime();
        const waitingElements = document.querySelectorAll('.message.waiting');
        
        waitingElements.forEach(element => {
            const waitingSince = parseInt(element.getAttribute('data-waiting-since'), 10);
            if (isNaN(waitingSince)) return;
            
            const elapsed = now - waitingSince;
            if (elapsed > processingTimeout) {
                // This message has been waiting too long, mark as error
                const contentSpan = element.querySelector('.message-content');
                if (contentSpan) {
                    contentSpan.textContent = "Lo siento, no he podido generar una respuesta a tiempo. Por favor, intenta reformular tu pregunta.";
                }
                element.classList.remove("waiting");
                element.classList.add("error");
                
                // Enable input for user to try again
                chatInput.disabled = false;
                
                // Remove from waiting list
                const messageId = element.getAttribute('data-id');
                if (messageId && waitingMessageIds.has(parseInt(messageId, 10))) {
                    waitingMessageIds.delete(parseInt(messageId, 10));
                }
            }
        });
    }

    function loadMessages() {
        if (!conversationId) return;
        
        // Check for timeout messages
        checkForTimeouts();
        
        fetch(`/chat/messages/?conversation_id=${conversationId}`, {
            headers: {
                "X-CSRFToken": csrftoken
            }
        })
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.json();
        })
        .then(data => {
            if (!data.messages || data.messages.length === 0) return;

            if (lastMessageId === 0) {
                // First load, clear container
                chatMessages.innerHTML = '';
            }
            
            const latestMessageId = Math.max(...data.messages.map(msg => msg.id));
            
            data.messages.forEach(message => {
                const existingMessage = document.querySelector(`[data-id="${message.id}"]`);
                
                if (existingMessage) {
                    if (message.direction === "OUT" && existingMessage.classList.contains("waiting") && message.content !== "Procesando respuesta...") {
                        updateExistingMessage(existingMessage, message);
                        showNotification("Nueva respuesta recibida");
                    }
                } else if (message.id > lastMessageId) {
                    chatMessages.appendChild(createMessageElement(message));
                    if (message.direction === "OUT" && message.content !== "Procesando respuesta...") {
                        showNotification("Nueva respuesta recibida");
                    }
                }
            });
            
            lastMessageId = latestMessageId;
            
            // Enable input if there are no waiting messages
            if (waitingMessageIds.size === 0 && document.querySelectorAll('.message.waiting').length === 0) {
                chatInput.disabled = false;
            }
            
            scrollToBottom();
        })
        .catch(error => {
            console.error("Error loading messages:", error);
            retryCount++;
            
            if (retryCount > maxRetries) {
                // Too many failed attempts, show error
                showNotification("Error de conexión. Refresca la página para intentar de nuevo.", true);
            }
        });
    }

    function showNotification(text, isError = false) {
        const notification = document.createElement("div");
        notification.classList.add("response-notification");
        if (isError) {
            notification.classList.add("error");
        }
        notification.textContent = text;
        document.body.appendChild(notification);

        const audio = new Audio("/static/sounds/notification.mp3");
        audio.play().catch(e => console.log('Error playing notification sound:', e));

        setTimeout(() => notification.remove(), 3000);
    }

    function startRefresh() {
        loadMessages(); // Initial load
        refreshTimer = setInterval(loadMessages, refreshInterval);
    }

    function stopRefresh() {
        if (refreshTimer) clearInterval(refreshTimer);
    }

    chatForm.addEventListener("submit", function (event) {
        event.preventDefault();
        const messageText = chatInput.value.trim();
        if (!messageText) return;

        chatInput.value = "";
        chatInput.disabled = true;

        const userMessage = createMessageElement({
            id: Date.now(), // Temporary ID
            direction: 'IN',
            content: messageText,
            timestamp: new Date()
        });

        const waitingMessage = createMessageElement({
            id: Date.now() + 1, // Temporary ID
            direction: 'OUT',
            content: 'Procesando respuesta...',
            timestamp: new Date()
        });
        waitingMessage.classList.add("waiting");

        chatMessages.appendChild(userMessage);
        chatMessages.appendChild(waitingMessage);
        scrollToBottom();

        fetch("/chat/send/", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrftoken
            },
            body: new URLSearchParams({
                'conversation_id': conversationId,
                'message': messageText
            })
        })
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.json();
        })
        .then(data => {
            // Add real message ID to the waiting set
            if (data.placeholder_id) {
                waitingMessageIds.add(data.placeholder_id);
                // Update our temporary waiting message with the real ID
                waitingMessage.setAttribute('data-id', data.placeholder_id);
            }
            
            if (data.conversation_id && !conversationId) {
                window.location.href = `/chat/?conversation_id=${data.conversation_id}`;
            }
        })
        .catch(error => {
            console.error("Error sending message:", error);
            waitingMessage.querySelector('.message-content').textContent = "Error al enviar el mensaje. Por favor, intenta de nuevo.";
            waitingMessage.classList.add("error");
            waitingMessage.classList.remove("waiting");
            chatInput.disabled = false;
        });
    });

    // Start auto-refresh
    startRefresh();
    
    // Stop refresh when user changes page
    window.addEventListener('beforeunload', stopRefresh);
    
    // Initial scroll to last message
    scrollToBottom();
});