// Chat functionality with optimized performance
class ChatManager {
    constructor() {
        this.conversationId = null;
        this.lastMessageId = null;
        this.messageCache = new Map();
        this.pollingInterval = 2000; // Start with 2 seconds
        this.pollingTimer = null;
        this.isProcessing = false;
        
        // Initialize chat when DOM is ready
        document.addEventListener('DOMContentLoaded', () => this.initializeChat());
    }
    
    initializeChat() {
        // Get conversation ID from the chat container
        const messagesContainer = document.getElementById('chat-messages');
        if (messagesContainer && messagesContainer.dataset.conversationId) {
            this.conversationId = messagesContainer.dataset.conversationId;
            
            // Only start polling if we have a valid conversation ID
            if (this.conversationId && this.conversationId !== 'None') {
                this.startMessagePolling();
            }
        }
        
        this.setupEventListeners();
        ChatManager.initializeStyles();
    }
    
    setupEventListeners() {
        const form = document.getElementById('chat-form');
        const input = document.getElementById('chat-input');
        
        // Throttled input handler
        input.addEventListener('input', this.throttle(() => {
            this.handleTyping();
        }, 500));
        
        // Form submission
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleSubmit(form);
        });
        
        // Handle visibility changes
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.pausePolling();
            } else {
                this.resumePolling();
            }
        });
    }
    
    throttle(func, limit) {
        return (...args) => {
            if (!this.throttleTimeout) {
                this.throttleTimeout = setTimeout(() => {
                    func.apply(this, args);
                    this.throttleTimeout = null;
                }, limit);
            }
        };
    }
    
    debounce(func, wait) {
        let timeout;
        return (...args) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }
    
    async handleSubmit(form) {
        const input = form.querySelector('input');
        const message = input.value.trim();
        
        if (!message) return;
        
        // Check if message requires confirmation
        if (this._requiresConfirmation(message)) {
            window.showConfirmation('¿Desea continuar con la iteración?', async (confirmed) => {
                if (confirmed) {
                    await this._sendUserMessage(message, input);
                }
            });
        } else {
            await this._sendUserMessage(message, input);
        }
    }
    
    showError(message) {
        // Create error toast element
        const toast = document.createElement('div');
        toast.className = 'error-toast';
        toast.textContent = message;
        document.body.appendChild(toast);
        
        // Add shake animation
        toast.classList.add('error-shake');
        
        // Remove after animation
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
    
    async _sendUserMessage(message, input) {
        let retryCount = 0;
        const maxRetries = 3;
        
        while (retryCount < maxRetries) {
            try {
                this._setLoadingState(true);
                
                // Optimistically add message to UI
                const tempId = `temp-${Date.now()}`;
                this.addMessageToUI({
                    id: tempId,
                    content: message,
                    direction: 'OUT',
                    timestamp: new Date().toISOString()
                }, true);
                
                input.value = '';
                
                // Send message to server
                const response = await this.sendMessage(message);
                
                if (response.requires_confirmation) {
                    // Handle confirmation flow
                    window.showConfirmation(
                        response.confirmation_message || '¿Desea continuar con la iteración?',
                        async (confirmed) => {
                            if (confirmed) {
                                try {
                                    const confirmResponse = await fetch('/chat/confirm-message/', {
                                        method: 'POST',
                                        headers: {
                                            'Content-Type': 'application/json',
                                            'X-CSRFToken': this.getCsrfToken()
                                        },
                                        body: JSON.stringify({
                                            conversation_id: this.conversationId,
                                            confirmed: true
                                        })
                                    });
                                    
                                    if (!confirmResponse.ok) {
                                        throw new Error('Failed to confirm message');
                                    }
                                    
                                    const result = await confirmResponse.json();
                                    this.updateMessageInUI(tempId, result);
                                    
                                } catch (error) {
                                    this.showError('Error al procesar la confirmación. Por favor, intenta de nuevo.');
                                    console.error('Confirmation error:', error);
                                }
                            } else {
                                // Remove temporary message if user cancels
                                const tempElement = document.getElementById(`message-${tempId}`);
                                if (tempElement) {
                                    tempElement.classList.add('fade-out');
                                    setTimeout(() => tempElement.remove(), 300);
                                }
                            }
                        }
                    );
                    return;
                }
                
                // Regular message flow
                if (response.id !== tempId) {
                    this.updateMessageInUI(tempId, response);
                }
                
                return;
                
            } catch (error) {
                retryCount++;
                
                if (error.name === 'TypeError' || error.message.includes('network')) {
                    // Network error
                    if (retryCount < maxRetries) {
                        // Wait before retrying (exponential backoff)
                        await new Promise(resolve => setTimeout(resolve, Math.pow(2, retryCount) * 1000));
                        continue;
                    }
                    this.showError('Error de conexión. Por favor, verifica tu conexión a internet.');
                } else {
                    this.showError('Error al enviar el mensaje. Por favor, intenta de nuevo.');
                }
                
                console.error('Error sending message:', error);
                
                // Remove temporary message on final error
                const tempElement = document.getElementById(`message-${tempId}`);
                if (tempElement) {
                    tempElement.classList.add('error-shake');
                    setTimeout(() => {
                        tempElement.classList.add('fade-out');
                        setTimeout(() => tempElement.remove(), 300);
                    }, 1000);
                }
            } finally {
                this._setLoadingState(false);
            }
        }
    }
    
    _requiresConfirmation(message) {
        // Add conditions that require confirmation
        const confirmationTriggers = [
            /continuar/i,
            /siguiente/i,
            /proceder/i,
            /avanzar/i,
            /confirmar/i
        ];
        
        return confirmationTriggers.some(trigger => trigger.test(message));
    }
    
    _setLoadingState(isLoading) {
        const loadingIndicator = document.getElementById('loading-indicator');
        const chatInput = document.getElementById('chat-input');
        const submitButton = document.querySelector('#chat-form button[type="submit"]');
        
        if (isLoading) {
            loadingIndicator.style.display = 'block';
            chatInput.disabled = true;
            submitButton.disabled = true;
        } else {
            loadingIndicator.style.display = 'none';
            chatInput.disabled = false;
            submitButton.disabled = false;
        }
    }
    
    async sendMessage(content) {
        // Function to get cookie value by name
        const getCookie = (name) => {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        };
        
        // Get the CSRF token
        const csrftoken = getCookie('csrftoken');
        
        const response = await fetch('/chat/send-message/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({
                content,
                conversation_id: this.conversationId
            }),
            credentials: 'same-origin'  // Include cookies in the request
        });
        
        if (!response.ok) {
            throw new Error(`Error ${response.status}: ${await response.text()}`);
        }
        
        return response.json();
    }
    
    async pollForMessages() {
        if (!this.conversationId || this.conversationId === 'None' || this.isProcessing) return;
        
        try {
            const response = await fetch(`/chat/messages/?conversation_id=${this.conversationId}&last_id=${this.lastMessageId || ''}`);
            const data = await response.json();
            
            if (data.messages && data.messages.length > 0) {
                // Update UI with new messages
                data.messages.forEach(message => {
                    if (!this.messageCache.has(message.id)) {
                        this.addMessageToUI(message);
                        this.messageCache.set(message.id, true);
                    }
                });
                
                // Update last message ID
                this.lastMessageId = data.messages[data.messages.length - 1].id;
            }
            
        } catch (error) {
            console.error('Error polling messages:', error);
            // Increase polling interval on error
            this.pollingInterval = Math.min(this.pollingInterval * 1.5, 10000);
        }
    }
    
    startMessagePolling() {
        this.pollInterval = setInterval(() => {
            this.pollForMessages();
        }, this.pollingInterval);
    }
    
    pausePolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
    }
    
    resumePolling() {
        this.startMessagePolling();
    }
    
    addMessageToUI(message, isTemporary = false) {
        const messagesContainer = document.getElementById('chat-messages');
        const messageElement = this.createMessageElement(message, isTemporary);
        
        // Use DocumentFragment for better performance
        const fragment = document.createDocumentFragment();
        fragment.appendChild(messageElement);
        
        // Append and scroll
        messagesContainer.appendChild(fragment);
        this.scrollToBottom();
    }
    
    createMessageElement(message, isTemporary) {
        const div = document.createElement('div');
        div.id = `message-${message.id}`;
        div.className = `message ${message.direction === 'IN' ? 'user' : 'bot'}`;
        if (isTemporary) div.classList.add('temporary');
        
        const content = document.createElement('span');
        content.className = 'message-content';
        content.textContent = message.content;
        
        const time = document.createElement('small');
        time.className = 'message-time';
        time.textContent = this.formatTimestamp(message.timestamp);
        
        div.appendChild(content);
        div.appendChild(time);
        
        return div;
    }
    
    updateMessageInUI(tempId, realMessage) {
        const tempElement = document.getElementById(`message-${tempId}`);
        if (tempElement) {
            const realElement = this.createMessageElement(realMessage);
            tempElement.replaceWith(realElement);
        }
    }
    
    scrollToBottom() {
        requestAnimationFrame(() => {
            const messagesContainer = document.getElementById('chat-messages');
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        });
    }
    
    handleTyping() {
        const now = Date.now();
        if (now - this.lastTypingUpdate > 1000) {
            this.lastTypingUpdate = now;
            // Implement typing indicator logic here if needed
        }
    }
    
    async prefetchTemplates() {
        // Prefetch any HTML templates or assets needed for messages
        try {
            const templateResponse = await fetch('/static/templates/message.html');
            const template = await templateResponse.text();
            this.messageTemplate = template;
        } catch (error) {
            console.warn('Could not prefetch templates:', error);
        }
    }
    
    formatTimestamp(timestamp) {
        return new Date(timestamp).toLocaleTimeString([], { 
            hour: '2-digit', 
            minute: '2-digit' 
        });
    }
    
    getCsrfToken() {
        const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (tokenInput) {
            return tokenInput.value;
        }
        
        // Fallback: try to get from cookie
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.startsWith('csrftoken=')) {
                return cookie.substring('csrftoken='.length, cookie.length);
            }
        }
        
        console.error('CSRF token not found');
        return '';
    }
    
    // Add error toast styles to the document
    static initializeStyles() {
        const style = document.createElement('style');
        style.textContent = `
            .error-toast {
                position: fixed;
                bottom: 20px;
                left: 50%;
                transform: translateX(-50%);
                background: #ff5252;
                color: white;
                padding: 12px 24px;
                border-radius: 4px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
                z-index: 1000;
                animation: slideUp 0.3s ease-out;
            }
            
            .error-shake {
                animation: shake 0.5s ease-in-out;
            }
            
            .fade-out {
                opacity: 0;
                transform: translateY(20px);
                transition: all 0.3s ease-out;
            }
            
            @keyframes slideUp {
                from {
                    opacity: 0;
                    transform: translate(-50%, 20px);
                }
                to {
                    opacity: 1;
                    transform: translate(-50%, 0);
                }
            }
            
            @keyframes shake {
                0%, 100% { transform: translateX(-50%); }
                25% { transform: translateX(-53%); }
                75% { transform: translateX(-47%); }
            }
        `;
        document.head.appendChild(style);
    }
}

// Initialize chat and styles when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    ChatManager.initializeStyles();
    window.chatManager = new ChatManager();
});