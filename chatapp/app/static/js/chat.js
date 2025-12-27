/**
 * Chat application JavaScript for HTMX ChatApp.
 * 
 * This module handles:
 * - Session ID management (generate, restore, clear)
 * - Chat message sending and SSE streaming
 * - Memory viewer functionality
 * - UI state management
 * 
 * Requirements: 3.1, 3.2, 3.3
 */

// ============================================================================
// Session Management
// ============================================================================

const SESSION_KEY = 'agentcore-session-id';
const MEMORY_COLLAPSED_KEY = 'agentcore-memory-collapsed';
const MODEL_SELECTION_KEY = 'agentcore-selected-model';

// ============================================================================
// Memory Cache
// Browser-side caching for AgentCore memory with localStorage persistence
// ============================================================================

const MEMORY_CACHE_KEY = 'agentcore-memory-cache';

/**
 * Cache for memory data to avoid constant API queries.
 * Persisted to localStorage to survive page refreshes.
 */
const memoryCache = {
    events: null,
    facts: null,
    summaries: null,
    preferences: null,
    sessionId: null,
};

/**
 * Load memory cache from localStorage.
 */
function loadMemoryCacheFromStorage() {
    try {
        const stored = localStorage.getItem(MEMORY_CACHE_KEY);
        if (stored) {
            const parsed = JSON.parse(stored);
            memoryCache.events = parsed.events || null;
            memoryCache.facts = parsed.facts || null;
            memoryCache.summaries = parsed.summaries || null;
            memoryCache.preferences = parsed.preferences || null;
            memoryCache.sessionId = parsed.sessionId || null;
            console.debug('Memory cache loaded from localStorage');
        }
    } catch (e) {
        console.warn('Failed to load memory cache from localStorage:', e);
    }
}

/**
 * Save memory cache to localStorage.
 */
function saveMemoryCacheToStorage() {
    try {
        localStorage.setItem(MEMORY_CACHE_KEY, JSON.stringify(memoryCache));
    } catch (e) {
        console.warn('Failed to save memory cache to localStorage:', e);
    }
}

/**
 * Clear all memory cache data.
 * Called when session changes or user clicks refresh.
 */
function clearMemoryCache() {
    memoryCache.events = null;
    memoryCache.facts = null;
    memoryCache.summaries = null;
    memoryCache.preferences = null;
    memoryCache.sessionId = null;
    localStorage.removeItem(MEMORY_CACHE_KEY);
    console.debug('Memory cache cleared');
}

/**
 * Check if cache is valid for the current session.
 * 
 * @returns {boolean} True if cache is valid for current session
 */
function isCacheValidForSession() {
    const currentSessionId = typeof getSessionId === 'function' ? getSessionId() : sessionId;
    return memoryCache.sessionId === currentSessionId;
}

// Load cache from localStorage on script load
loadMemoryCacheFromStorage();

// ============================================================================
// Model Selection
// Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.8, 10.9
// ============================================================================

/**
 * Available AI models for selection.
 * Each model has an id (model identifier), name (display name), and description.
 * 
 * Requirements: 10.3
 */
const AVAILABLE_MODELS = [
    {
        id: "global.amazon.nova-2-lite-v1:0",
        name: "Nova 2 Lite",
        description: "IN [$0.30] - OUT [$2.50]"
    },
    {
        id: "us.amazon.nova-pro-v1:0",
        name: "Nova Pro",
        description: "IN [$0.80] - OUT [$3.20]"
    },
    {
        id: "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        name: "Claude Haiku 4.5",
        description: "IN [$1.00] - OUT [$5.00]"
    },
    {
        id: "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        name: "Claude Sonnet 4.5",
        description: "IN [$3.00] - OUT [$15.00]"
    },
    {
        id: "global.anthropic.claude-opus-4-5-20251101-v1:0",
        name: "Claude Opus 4.5",
        description: "IN [$5.00] - OUT [$25.00]"
    }
];

/**
 * Default model ID when no selection is stored.
 * 
 * Requirements: 10.8
 */
const DEFAULT_MODEL_ID = "global.amazon.nova-2-lite-v1:0";

/**
 * Get the currently selected model from localStorage.
 * Returns the default model (Nova 2 Lite) if no selection is stored.
 * 
 * @returns {Object} The selected model object with id, name, description
 * 
 * Requirements: 10.8, 10.9
 */
function getSelectedModel() {
    const storedModelId = localStorage.getItem(MODEL_SELECTION_KEY);
    
    if (storedModelId) {
        const model = AVAILABLE_MODELS.find(m => m.id === storedModelId);
        if (model) {
            return model;
        }
    }
    
    // Return default model (Nova 2 Lite)
    return AVAILABLE_MODELS.find(m => m.id === DEFAULT_MODEL_ID) || AVAILABLE_MODELS[0];
}

/**
 * Set the selected model and persist to localStorage.
 * 
 * @param {string} modelId - The model identifier to select
 * 
 * Requirements: 10.9
 */
function setSelectedModel(modelId) {
    const model = AVAILABLE_MODELS.find(m => m.id === modelId);
    if (!model) {
        console.error('Invalid model ID:', modelId);
        return;
    }
    
    localStorage.setItem(MODEL_SELECTION_KEY, modelId);
    console.log('Model selection saved:', model.name);
}

/**
 * Toggle the model dropdown visibility.
 * 
 * Requirements: 10.2
 */
function toggleModelDropdown() {
    const dropdown = document.getElementById('model-dropdown');
    if (!dropdown) return;
    
    const isHidden = dropdown.classList.contains('hidden');
    
    if (isHidden) {
        // Populate options before showing
        populateModelOptions();
        dropdown.classList.remove('hidden');
        
        // Add click outside listener to close dropdown
        setTimeout(() => {
            document.addEventListener('click', closeModelDropdownOnClickOutside);
        }, 0);
    } else {
        dropdown.classList.add('hidden');
        document.removeEventListener('click', closeModelDropdownOnClickOutside);
    }
}

/**
 * Close the model dropdown when clicking outside.
 * 
 * @param {Event} event - Click event
 */
function closeModelDropdownOnClickOutside(event) {
    const dropdown = document.getElementById('model-dropdown');
    const button = document.getElementById('model-selector-btn');
    
    if (!dropdown || !button) return;
    
    if (!dropdown.contains(event.target) && !button.contains(event.target)) {
        dropdown.classList.add('hidden');
        document.removeEventListener('click', closeModelDropdownOnClickOutside);
    }
}

/**
 * Populate the model dropdown with available options.
 * Highlights the currently selected model.
 */
function populateModelOptions() {
    const optionsContainer = document.getElementById('model-options');
    if (!optionsContainer) return;
    
    const selectedModel = getSelectedModel();
    
    // Clear existing options
    optionsContainer.innerHTML = '';
    
    // Add each model as an option
    AVAILABLE_MODELS.forEach(model => {
        const isSelected = model.id === selectedModel.id;
        
        const option = document.createElement('button');
        option.type = 'button';
        option.className = `w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors flex items-start gap-3 ${isSelected ? 'bg-primary-50' : ''}`;
        option.onclick = () => selectModel(model.id);
        
        // Create checkmark indicator
        const checkmark = document.createElement('div');
        checkmark.className = 'w-5 h-5 flex-shrink-0 mt-0.5';
        if (isSelected) {
            checkmark.innerHTML = `
                <svg class="w-5 h-5 text-primary-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                </svg>
            `;
        }
        
        // Create model info
        const info = document.createElement('div');
        info.className = 'flex-1 min-w-0';
        
        const name = document.createElement('div');
        name.className = `text-sm font-medium ${isSelected ? 'text-primary-700' : 'text-gray-900'}`;
        name.textContent = model.name;
        
        const description = document.createElement('div');
        description.className = 'text-xs text-gray-500 truncate';
        description.textContent = model.description;
        
        info.appendChild(name);
        info.appendChild(description);
        
        option.appendChild(checkmark);
        option.appendChild(info);
        optionsContainer.appendChild(option);
    });
}

/**
 * Select a model and update the UI.
 * 
 * @param {string} modelId - The model identifier to select
 * 
 * Requirements: 10.4
 */
function selectModel(modelId) {
    // Save selection
    setSelectedModel(modelId);
    
    // Update UI
    updateModelSelectorUI();
    
    // Close dropdown
    const dropdown = document.getElementById('model-dropdown');
    if (dropdown) {
        dropdown.classList.add('hidden');
        document.removeEventListener('click', closeModelDropdownOnClickOutside);
    }
}

/**
 * Update the model selector button to show the currently selected model.
 * 
 * Requirements: 10.4
 */
function updateModelSelectorUI() {
    const selectedModel = getSelectedModel();
    const nameSpan = document.getElementById('selected-model-name');
    
    if (nameSpan) {
        nameSpan.textContent = selectedModel.name;
    }
}

/**
 * Initialize model selection on page load.
 * Restores saved selection or uses default.
 */
function initializeModelSelection() {
    updateModelSelectorUI();
    console.log('Model selection initialized:', getSelectedModel().name);
}

// ============================================================================
// Prompt Templates
// Requirements: 1.1, 1.2, 1.3, 1.4
// ============================================================================

const TEMPLATES_CACHE_KEY = 'agentcore-templates-cache';

/**
 * Cached templates loaded from the API or localStorage.
 */
let cachedTemplates = null;

/**
 * Load templates from localStorage.
 */
function loadTemplatesFromStorage() {
    try {
        const stored = localStorage.getItem(TEMPLATES_CACHE_KEY);
        if (stored) {
            cachedTemplates = JSON.parse(stored);
            console.debug('Templates loaded from localStorage:', cachedTemplates.length);
        }
    } catch (e) {
        console.warn('Failed to load templates from localStorage:', e);
    }
}

/**
 * Save templates to localStorage.
 */
function saveTemplatesToStorage() {
    try {
        if (cachedTemplates) {
            localStorage.setItem(TEMPLATES_CACHE_KEY, JSON.stringify(cachedTemplates));
        }
    } catch (e) {
        console.warn('Failed to save templates to localStorage:', e);
    }
}

/**
 * Clear templates cache (called when admin updates templates).
 */
function clearTemplatesCache() {
    cachedTemplates = null;
    localStorage.removeItem(TEMPLATES_CACHE_KEY);
    console.debug('Templates cache cleared');
}

// Load templates from localStorage on script load
loadTemplatesFromStorage();

/**
 * Fetch prompt templates from the API.
 * Uses localStorage cache, falls back to API if not cached.
 * 
 * @param {boolean} forceRefresh - If true, bypass cache and fetch from API
 * @returns {Promise<Array>} Array of template objects
 * 
 * Requirements: 1.2
 */
async function fetchTemplates(forceRefresh = false) {
    // Return cached templates if available and not forcing refresh
    if (!forceRefresh && cachedTemplates !== null) {
        return cachedTemplates;
    }
    
    try {
        const response = await fetch('/api/templates');
        if (!response.ok) {
            throw new Error(`Failed to fetch templates: ${response.status}`);
        }
        
        cachedTemplates = await response.json();
        saveTemplatesToStorage();
        console.debug('Templates loaded from API:', cachedTemplates.length);
        return cachedTemplates;
    } catch (error) {
        console.error('Error fetching templates:', error);
        // Return cached templates if API fails
        return cachedTemplates || [];
    }
}

/**
 * Toggle the templates dropdown visibility.
 * Loads templates from API when opening.
 * 
 * Requirements: 1.2
 */
async function toggleTemplatesDropdown() {
    const dropdown = document.getElementById('templates-dropdown');
    if (!dropdown) return;
    
    const isHidden = dropdown.classList.contains('hidden');
    
    if (isHidden) {
        // Load and populate templates before showing
        await populateTemplatesOptions();
        dropdown.classList.remove('hidden');
        
        // Add click outside listener to close dropdown
        setTimeout(() => {
            document.addEventListener('click', closeTemplatesDropdownOnClickOutside);
        }, 0);
    } else {
        dropdown.classList.add('hidden');
        document.removeEventListener('click', closeTemplatesDropdownOnClickOutside);
    }
}

/**
 * Close the templates dropdown when clicking outside.
 * 
 * @param {Event} event - Click event
 */
function closeTemplatesDropdownOnClickOutside(event) {
    const dropdown = document.getElementById('templates-dropdown');
    const button = document.getElementById('templates-btn');
    
    if (!dropdown || !button) return;
    
    if (!dropdown.contains(event.target) && !button.contains(event.target)) {
        dropdown.classList.add('hidden');
        document.removeEventListener('click', closeTemplatesDropdownOnClickOutside);
    }
}

/**
 * Populate the templates dropdown with available options.
 * Shows title prominently and description as secondary text.
 * 
 * Requirements: 1.2, 5.1
 */
async function populateTemplatesOptions() {
    const optionsContainer = document.getElementById('templates-options');
    if (!optionsContainer) return;
    
    // Show loading state
    optionsContainer.innerHTML = '<div class="px-3 py-2 text-sm text-gray-500">Loading templates...</div>';
    
    // Fetch templates
    const templates = await fetchTemplates();
    
    // Clear loading state
    optionsContainer.innerHTML = '';
    
    if (templates.length === 0) {
        optionsContainer.innerHTML = '<div class="px-3 py-2 text-sm text-gray-500">No templates available</div>';
        return;
    }
    
    // Add each template as an option (Requirements 1.2, 5.1)
    templates.forEach(template => {
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors flex flex-col gap-0.5';
        option.onclick = () => selectTemplate(template.prompt_detail);
        
        // Title - shown prominently (Requirement 5.1)
        const title = document.createElement('div');
        title.className = 'text-sm font-medium text-gray-900';
        title.textContent = template.title;
        
        // Description - secondary text (Requirement 5.1)
        const description = document.createElement('div');
        description.className = 'text-xs text-gray-500 truncate';
        description.textContent = template.description;
        
        option.appendChild(title);
        option.appendChild(description);
        optionsContainer.appendChild(option);
    });
}

/**
 * Select a template and insert its prompt_detail into the chat input.
 * Closes the dropdown after selection.
 * 
 * @param {string} promptDetail - The prompt text to insert
 * 
 * Requirements: 1.3, 1.4
 */
function selectTemplate(promptDetail) {
    // Insert prompt_detail into chat input (Requirement 1.3)
    const input = document.getElementById('message-input');
    if (input) {
        input.value = promptDetail;
        input.focus();
        // Trigger auto-resize for textarea
        autoResizeTextarea(input);
    }
    
    // Close dropdown (Requirement 1.4)
    const dropdown = document.getElementById('templates-dropdown');
    if (dropdown) {
        dropdown.classList.add('hidden');
        document.removeEventListener('click', closeTemplatesDropdownOnClickOutside);
    }
}

/**
 * Clear the cached templates.
 * Call this when templates are updated via admin.
 */
function clearTemplatesCache() {
    cachedTemplates = null;
}

/**
 * Prefetch templates in the background on page load.
 * This ensures templates are ready when the user clicks the templates button.
 * Returns a promise that resolves when templates are loaded.
 * 
 * Requirements: 1.2
 */
function prefetchTemplates() {
    return fetchTemplates().then(() => {
        console.debug('Templates prefetched');
    }).catch(err => {
        console.warn('Failed to prefetch templates:', err);
        // Don't rethrow - allow memory to load even if templates fail
    });
}

/**
 * Configuration for tool display.
 */
const TOOLS_CONFIG = {
    maxVisibleTools: 2,  // Number of tools to show before "Show more" button
};

/**
 * Current session ID for the chat conversation.
 * Restored from localStorage on page load or generated fresh.
 */
let sessionId = null;

/**
 * Flag indicating if a message is currently being streamed.
 */
let isStreaming = false;

/**
 * Generate a new UUID v4 session ID.
 * 
 * @returns {string} A new UUID v4 string
 */
function generateSessionId() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

/**
 * Initialize session on page load.
 * Restores existing session from localStorage or generates a new one.
 * 
 * Requirements: 3.1
 */
function initializeSession() {
    const storedSessionId = localStorage.getItem(SESSION_KEY);
    
    if (storedSessionId) {
        sessionId = storedSessionId;
        console.log('Session restored:', sessionId);
    } else {
        sessionId = generateSessionId();
        localStorage.setItem(SESSION_KEY, sessionId);
        console.log('New session created:', sessionId);
    }
}

/**
 * Get the current session ID.
 * 
 * @returns {string} The current session ID
 */
function getSessionId() {
    if (!sessionId) {
        initializeSession();
    }
    return sessionId;
}

/**
 * Clear the current session and generate a new one.
 * Used when starting a new chat conversation.
 * 
 * Requirements: 3.2
 */
function clearAndCreateNewSession() {
    sessionId = generateSessionId();
    localStorage.setItem(SESSION_KEY, sessionId);
    console.log('Session cleared, new session:', sessionId);
    return sessionId;
}

/**
 * Start a new chat conversation.
 * Clears the message history and generates a new session ID.
 * 
 * Requirements: 3.2
 */
function startNewChat() {
    // Generate new session ID
    clearAndCreateNewSession();
    
    // Clear memory cache for new session
    clearMemoryCache();
    
    // Clear message list using safe DOM manipulation (avoids innerHTML XSS risks)
    const messageList = document.getElementById('message-list');
    if (messageList) {
        // Clear existing content
        messageList.textContent = '';
        
        // Build empty state using DOM APIs
        const emptyState = document.createElement('div');
        emptyState.id = 'empty-state';
        emptyState.className = 'flex items-center justify-center h-full p-10';
        
        const textCenter = document.createElement('div');
        textCenter.className = 'text-center';
        
        // Add welcome message if user email is available
        if (window.userEmail) {
            const welcomeP = document.createElement('p');
            welcomeP.className = 'text-gray-700 text-lg font-medium mb-2';
            welcomeP.textContent = `Welcome, ${window.userEmail}`;
            textCenter.appendChild(welcomeP);
        }
        
        // Add instruction text (use configurable welcome message)
        const instructionP = document.createElement('p');
        instructionP.className = 'text-gray-500 text-base';
        instructionP.textContent = window.welcomeMessage || 'Start a conversation by typing a message below';
        textCenter.appendChild(instructionP);
        
        emptyState.appendChild(textCenter);
        messageList.appendChild(emptyState);
    }
    
    // Clear error
    hideError();
    
    // Refresh memory for new session
    refreshMemory();
}

// ============================================================================
// Chat Messaging
// ============================================================================

/**
 * Send a chat message to the backend.
 * Handles form submission, SSE streaming, and UI updates.
 * 
 * @param {Event} event - Form submit event
 * 
 * Requirements: 2.1, 2.2, 2.3, 2.6, 2.7, 3.3
 */
async function sendMessage(event) {
    event.preventDefault();
    
    const input = document.getElementById('message-input');
    const message = input.value.trim();
    
    if (!message || isStreaming) return;
    
    // Store message for potential retry
    lastFailedMessage = message;
    
    // Hide empty state
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.remove();
    
    // Hide any previous errors
    hideError();
    
    // Add user message to the list
    addMessage('user', message);
    
    // Add user message to memory cache
    if (typeof addMessageToEventCache === 'function') {
        addMessageToEventCache('user', message);
    }
    
    // Clear input and reset textarea height
    input.value = '';
    input.style.height = 'auto';
    
    // Set connecting state - waiting for runtime provisioning
    setConnectionState('connecting');
    
    // Create assistant message placeholder
    const assistantMsgId = 'msg-assistant-' + Date.now();
    addStreamingMessage(assistantMsgId);
    
    try {
        // Send message via POST to /api/chat endpoint (Requirement 2.1, 2.2)
        // Includes session_id per Requirement 3.3
        // Includes model_id per Requirement 10.5
        const selectedModel = getSelectedModel();
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                prompt: message,
                session_id: getSessionId(),
                model_id: selectedModel.id
            })
        });
        
        // Handle 401 - session expired, redirect to login
        if (response.status === 401) {
            console.log('Session expired, redirecting to login');
            window.location.href = '/auth/login?error=session_expired';
            return;
        }
        
        if (!response.ok) {
            const errorText = await response.text().catch(() => '');
            let errorMessage = `Request failed with status ${response.status}`;
            
            // Try to parse error response
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage = errorJson.detail || errorJson.message || errorMessage;
            } catch {
                if (errorText) errorMessage = errorText;
            }
            
            throw new Error(errorMessage);
        }
        
        // Process SSE stream (Requirement 2.3 - render incrementally)
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullContent = '';
        let hasReceivedContent = false;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    
                    // Handle done event (Requirement 2.6 - completion indicator)
                    if (data === '[DONE]') {
                        finalizeMessage(assistantMsgId, fullContent);
                        // Add assistant message to memory cache
                        if (typeof addMessageToEventCache === 'function' && fullContent) {
                            addMessageToEventCache('assistant', fullContent);
                        }
                        hasReceivedContent = true;
                        fullContent = ''; // Clear to prevent double finalization
                        continue;
                    }
                    
                    try {
                        const sseEvent = JSON.parse(data);
                        
                        // Transition to streaming state once we receive any valid event
                        if (!hasReceivedContent && sseEvent.type) {
                            setConnectionState('streaming');
                        }
                        
                        fullContent = handleSSEEvent(sseEvent, assistantMsgId, fullContent);
                        hasReceivedContent = true;
                    } catch (e) {
                        console.error('Failed to parse SSE event:', e, 'Data:', data);
                    }
                }
            }
        }
        
        // Finalize if we received content but no explicit [DONE]
        if (hasReceivedContent && fullContent) {
            finalizeMessage(assistantMsgId, fullContent);
            // Add assistant message to memory cache
            if (typeof addMessageToEventCache === 'function') {
                addMessageToEventCache('assistant', fullContent);
            }
        }
        
        // Clear the failed message since we succeeded
        lastFailedMessage = null;
        
        // Note: Memory is updated via cache during conversation
        // Full refresh only happens on page load or manual refresh button click
        
    } catch (error) {
        console.error('Chat error:', error);
        
        // Set error state
        setConnectionState('error');
        
        // Display error with retry option (Requirement 2.7)
        const errorMessage = error.message || 'Failed to send message';
        const isNetworkError = error.name === 'TypeError' || errorMessage.includes('fetch');
        
        if (isNetworkError) {
            showError('Network error. Please check your connection and try again.', errorMessage);
        } else {
            showError(errorMessage);
        }
        
        // Remove the streaming message placeholder
        removeMessage(assistantMsgId);
        
        // Return early - don't reset to ready state yet
        return;
    }
    
    // Reset to ready state on success
    setConnectionState('ready');
}

/**
 * Check if a tool result indicates an error.
 * Detects common error patterns in tool results.
 * 
 * @param {Object|string} toolResult - The tool result to check
 * @returns {boolean} True if the result indicates an error
 */
function isToolResultError(toolResult) {
    if (!toolResult) return false;
    
    // If it's a string, check for error patterns
    if (typeof toolResult === 'string') {
        const lowerResult = toolResult.toLowerCase();
        return lowerResult.includes('"success": false') ||
               lowerResult.includes('"error":') ||
               lowerResult.includes('error:') ||
               lowerResult.startsWith('error');
    }
    
    // If it's an object, check for error indicators
    if (typeof toolResult === 'object') {
        // Check for explicit success: false
        if (toolResult.success === false) return true;
        // Check for error field
        if (toolResult.error !== undefined && toolResult.error !== null) return true;
        // Check for isError field
        if (toolResult.isError === true) return true;
        // Check for status field indicating error
        if (toolResult.status === 'error' || toolResult.status === 'failed') return true;
    }
    
    return false;
}

/**
 * Format an object or JSON string as key-value pairs, one per line.
 * 
 * @param {Object|string} data - The data to format
 * @returns {string} Formatted key-value pairs
 */
function formatAsKeyValuePairs(data) {
    if (!data) return '';
    
    let obj = data;
    if (typeof data === 'string') {
        try {
            obj = JSON.parse(data);
        } catch (e) {
            return data; // Return as-is if not valid JSON
        }
    }
    
    if (typeof obj !== 'object' || obj === null) {
        return String(obj);
    }
    
    const lines = [];
    for (const [key, value] of Object.entries(obj)) {
        let displayValue;
        if (value === null) {
            displayValue = 'null';
        } else if (typeof value === 'object') {
            displayValue = JSON.stringify(value);
        } else if (typeof value === 'string') {
            displayValue = value;
        } else {
            displayValue = String(value);
        }
        lines.push(`${key}: ${displayValue}`);
    }
    return lines.join('\n');
}

/**
 * Handle an SSE event from the chat stream.
 * Processes different event types and updates the UI accordingly.
 * 
 * @param {Object} event - Parsed SSE event
 * @param {string} msgId - Message element ID
 * @param {string} currentContent - Current accumulated content
 * @returns {string} Updated content
 * 
 * Requirements: 2.3, 2.4, 2.5, 2.6, 2.7
 */
function handleSSEEvent(event, msgId, currentContent) {
    const msgElement = document.getElementById(msgId);
    if (!msgElement) return currentContent;
    
    const contentDiv = msgElement.querySelector('.message-content');
    
    switch (event.type) {
        case 'message':
            // Filter out thinking tags (Requirement 2.6 - streaming indicator)
            let content = event.content || '';
            content = filterThinkingTags(content);
            currentContent += content;
            
            // Render markdown (Requirement 2.3 - render message content incrementally)
            // Content is sanitized by DOMPurify before rendering to prevent XSS
            // The content comes from our trusted AgentCore backend, not direct user input
            if (typeof marked !== 'undefined') {
                // nosemgrep: insecure-innerhtml
                contentDiv.innerHTML = DOMPurify.sanitize(marked.parse(currentContent));
            } else {
                contentDiv.textContent = currentContent;
            }
            contentDiv.classList.add('markdown-content');
            
            // Add streaming cursor at the end while still streaming
            // Remove any existing cursor first to avoid duplicates
            const existingCursor = contentDiv.querySelector('.streaming-cursor');
            if (existingCursor) existingCursor.remove();
            const cursor = document.createElement('span');
            cursor.className = 'streaming-cursor';
            contentDiv.appendChild(cursor);
            
            // Auto-scroll to keep latest content visible
            scrollToBottom();
            break;
            
        case 'tool_use':
            // Display tool usage indicator (Requirement 2.4)
            // Insert into tools-container so it doesn't get overwritten by message content
            const toolsContainer = msgElement.querySelector('.tools-container');
            if (!toolsContainer) break;
            
            const toolUseId = event.tool_use_id || 'tool-' + Date.now();
            // Check if this tool is already displayed
            if (toolsContainer.querySelector(`[data-tool-id="${toolUseId}"]`)) break;
            
            // Format tool input for display as key-value pairs
            const toolInputJson = event.tool_input ? JSON.stringify(event.tool_input, null, 2) : '';
            const toolInputDisplay = event.tool_input ? formatAsKeyValuePairs(event.tool_input) : 'No input';
            
            const toolUseHtml = `
                <div id="tool-${escapeHtml(toolUseId)}" class="tool-card border rounded-lg overflow-hidden bg-primary-50 border-primary-200 my-1" data-tool-id="${escapeHtml(toolUseId)}" data-tool-name="${escapeHtml(event.tool_name)}" data-tool-input="${escapeHtml(toolInputJson)}">
                    <button onclick="toggleToolExpand(this)" class="tool-header w-full px-3 py-2 flex items-center gap-2 hover:bg-white/50 transition-colors">
                        <svg class="tool-icon w-4 h-4 text-primary-600 spin shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
                        </svg>
                        <span class="hidden sm:inline text-xs text-gray-500 font-medium shrink-0">Tool:</span>
                        <span class="tool-name font-mono text-xs font-medium text-gray-700 truncate">${escapeHtml(event.tool_name)}</span>
                        <span class="tool-status text-xs font-medium text-primary-600 ml-auto shrink-0 hidden sm:inline">Running...</span>
                        <svg class="tool-status-icon w-4 h-4 text-primary-600 ml-auto shrink-0 sm:hidden spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        <svg class="expand-icon w-4 h-4 text-gray-500 transition-transform shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                        </svg>
                    </button>
                    <div class="tool-details hidden border-t border-gray-200 bg-white/70">
                        <div class="px-4 py-3 border-b border-gray-200">
                            <div class="flex items-center justify-between mb-2">
                                <h4 class="text-xs font-semibold text-gray-700 flex items-center gap-1">
                                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                                    </svg>
                                    Input Parameters
                                </h4>
                                <button onclick="copyToClipboard(this, '${escapeHtml(toolInputJson).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'); event.stopPropagation();" class="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                    </svg>
                                    Copy
                                </button>
                            </div>
                            <pre class="text-xs bg-gray-50 p-2 rounded border border-gray-200 overflow-x-auto whitespace-pre-wrap break-words"><code class="text-gray-800">${escapeHtml(toolInputDisplay)}</code></pre>
                        </div>
                        <div class="tool-result-section px-4 py-3 hidden">
                            <div class="flex items-center justify-between mb-2">
                                <h4 class="text-xs font-semibold text-gray-700 flex items-center gap-1">
                                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                                    </svg>
                                    Tool Result
                                </h4>
                                <button class="copy-result-btn text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                    </svg>
                                    Copy
                                </button>
                            </div>
                            <pre class="tool-result-content text-xs bg-gray-50 p-2 rounded border border-gray-200 overflow-x-auto max-h-64 whitespace-pre-wrap break-words"><code class="text-gray-800">Waiting for result...</code></pre>
                        </div>
                    </div>
                </div>
            `;
            toolsContainer.insertAdjacentHTML('beforeend', toolUseHtml);
            updateToolsVisibility(toolsContainer);
            scrollToBottom();
            break;
            
        case 'tool_result':
            // Display tool result and update indicator (Requirement 2.5)
            const toolsContainerForResult = msgElement.querySelector('.tools-container');
            if (!toolsContainerForResult) break;
            
            const resultToolId = event.tool_use_id;
            let toolCard = null;
            
            // Find the matching tool card by ID
            if (resultToolId) {
                toolCard = toolsContainerForResult.querySelector(`[data-tool-id="${resultToolId}"]`);
            }
            
            // Fallback to last card if no match found
            if (!toolCard) {
                const toolCards = toolsContainerForResult.querySelectorAll('.tool-card');
                if (toolCards.length > 0) {
                    toolCard = toolCards[toolCards.length - 1];
                }
            }
            
            // Check if the tool result indicates an error
            const isToolError = isToolResultError(event.tool_result);
            
            // Update the card to show completion or error (only if not already completed)
            if (toolCard && !toolCard.classList.contains('completed')) {
                toolCard.classList.add('completed');
                toolCard.classList.remove('bg-primary-50', 'border-primary-200');
                
                const toolIcon = toolCard.querySelector('.tool-icon');
                const statusSpan = toolCard.querySelector('.tool-status');
                const statusIcon = toolCard.querySelector('.tool-status-icon');
                
                if (isToolError) {
                    // Error styling - red theme
                    toolCard.classList.add('bg-red-50', 'border-red-200');
                    
                    if (toolIcon) {
                        toolIcon.classList.remove('spin', 'text-primary-600');
                        toolIcon.classList.add('text-red-600');
                    }
                    
                    if (statusSpan) {
                        statusSpan.classList.remove('text-primary-600');
                        statusSpan.classList.add('text-red-600');
                        statusSpan.textContent = 'Error';
                    }
                    
                    if (statusIcon) {
                        statusIcon.classList.remove('text-primary-600', 'spin');
                        statusIcon.classList.add('text-red-600');
                        // X icon for error
                        statusIcon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />';
                    }
                } else {
                    // Success styling - blue theme
                    toolCard.classList.add('bg-blue-50', 'border-blue-200');
                    
                    if (toolIcon) {
                        toolIcon.classList.remove('spin', 'text-primary-600');
                        toolIcon.classList.add('text-blue-600');
                    }
                    
                    if (statusSpan) {
                        statusSpan.classList.remove('text-primary-600');
                        statusSpan.classList.add('text-blue-600');
                        statusSpan.textContent = 'Completed';
                    }
                    
                    if (statusIcon) {
                        statusIcon.classList.remove('text-primary-600', 'spin');
                        statusIcon.classList.add('text-blue-600');
                        // Checkmark icon for success
                        statusIcon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />';
                    }
                }
                
                // Show and populate tool result section
                const resultSection = toolCard.querySelector('.tool-result-section');
                const resultContent = toolCard.querySelector('.tool-result-content code');
                if (resultSection && resultContent && event.tool_result) {
                    resultSection.classList.remove('hidden');
                    // Format as key-value pairs for display
                    const resultDisplay = formatAsKeyValuePairs(event.tool_result);
                    // Keep original JSON for copy button
                    const resultJson = typeof event.tool_result === 'string' 
                        ? event.tool_result 
                        : JSON.stringify(event.tool_result, null, 2);
                    resultContent.textContent = resultDisplay;
                    
                    // Set up copy button for result (copies original JSON)
                    const copyBtn = resultSection.querySelector('.copy-result-btn');
                    if (copyBtn) {
                        copyBtn.onclick = (e) => {
                            e.stopPropagation();
                            copyToClipboard(copyBtn, resultJson);
                        };
                    }
                }
            }
            scrollToBottom();
            break;
            
        case 'error':
            // Display error message with retry option (Requirement 2.7)
            const errorMessage = event.message || 'An error occurred';
            const errorDetails = event.details || '';
            showError(errorMessage, errorDetails);
            break;
            
        case 'done':
            // Handle done event (Requirement 2.6 - completion indicator)
            // This is handled in the main sendMessage function via [DONE] marker
            break;
            
        case 'metadata':
            // Store metadata for potential display (token usage, etc.)
            // Metadata can come as event.data or event.usage
            const usageData = event.data || event.usage || event;
            if (usageData && (usageData.inputTokens !== undefined || usageData.outputTokens !== undefined || usageData.latencyMs !== undefined)) {
                msgElement.dataset.tokenUsage = JSON.stringify(usageData);
            }
            break;
            
        case 'guardrail':
            // Handle guardrail violation events (Requirements 4.1, 4.2)
            // Store guardrail data on the appropriate message element
            handleGuardrailEvent(event, msgId);
            break;
    }
    
    return currentContent;
}

// ============================================================================
// Guardrail UI Indicators
// Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
// ============================================================================

/**
 * Handle a guardrail event from the SSE stream.
 * Stores guardrail data on the message element and displays warning indicator.
 * 
 * @param {Object} event - Guardrail event with source, action, assessments
 * @param {string} msgId - Current assistant message ID
 * 
 * Requirements: 4.1, 4.2
 */
function handleGuardrailEvent(event, msgId) {
    const { source, action, assessments } = event;
    
    // Only process if there was an intervention
    if (action !== 'GUARDRAIL_INTERVENED') return;
    
    // Find the target message element based on source
    let targetElement;
    if (source === 'OUTPUT') {
        // For OUTPUT, attach to the current assistant message
        targetElement = document.getElementById(msgId);
    } else if (source === 'INPUT') {
        // For INPUT, find the most recent user message
        const messageList = document.getElementById('message-list');
        if (messageList) {
            const userMessages = messageList.querySelectorAll('[id^="msg-user-"]');
            if (userMessages.length > 0) {
                targetElement = userMessages[userMessages.length - 1];
            }
        }
    }
    
    if (!targetElement) return;
    
    // Store guardrail data on the element for later reference
    targetElement.dataset.guardrailSource = source;
    targetElement.dataset.guardrailAction = action;
    targetElement.dataset.guardrailAssessments = JSON.stringify(assessments);
    
    // Extract policy types from assessments
    const policyTypes = extractPolicyTypes(assessments);
    
    // Add guardrail indicator to the message
    addGuardrailIndicator(targetElement, source, policyTypes, assessments);
}

/**
 * Extract policy types from guardrail assessments.
 * 
 * @param {Array} assessments - Array of assessment objects from ApplyGuardrail
 * @returns {Array} Array of policy type strings
 */
function extractPolicyTypes(assessments) {
    const policyTypes = [];
    
    if (!assessments || !Array.isArray(assessments)) return policyTypes;
    
    assessments.forEach(assessment => {
        // Content policy filter
        if (assessment.contentPolicy) {
            const filters = assessment.contentPolicy.filters || [];
            filters.forEach(filter => {
                if (filter.action === 'BLOCKED' || filter.confidence) {
                    policyTypes.push(`Content: ${filter.type || 'Unknown'}`);
                }
            });
        }
        
        // Topic policy
        if (assessment.topicPolicy) {
            const topics = assessment.topicPolicy.topics || [];
            topics.forEach(topic => {
                if (topic.action === 'BLOCKED') {
                    policyTypes.push(`Topic: ${topic.name || 'Denied topic'}`);
                }
            });
        }
        
        // Word policy
        if (assessment.wordPolicy) {
            const customWords = assessment.wordPolicy.customWords || [];
            const managedWordLists = assessment.wordPolicy.managedWordLists || [];
            if (customWords.length > 0 || managedWordLists.length > 0) {
                policyTypes.push('Word policy');
            }
        }
        
        // Sensitive information policy
        if (assessment.sensitiveInformationPolicy) {
            const piiEntities = assessment.sensitiveInformationPolicy.piiEntities || [];
            const regexes = assessment.sensitiveInformationPolicy.regexes || [];
            if (piiEntities.length > 0 || regexes.length > 0) {
                policyTypes.push('Sensitive information');
            }
        }
    });
    
    return [...new Set(policyTypes)]; // Remove duplicates
}

/**
 * Add a guardrail warning indicator to a message element.
 * 
 * @param {HTMLElement} msgElement - The message container element
 * @param {string} source - "INPUT" or "OUTPUT"
 * @param {Array} policyTypes - Array of triggered policy type strings
 * @param {Array} assessments - Full assessments array for details view
 * 
 * Requirements: 4.3, 4.5
 */
function addGuardrailIndicator(msgElement, source, policyTypes, assessments) {
    // Check if indicator already exists
    if (msgElement.querySelector('.guardrail-indicator')) return;
    
    // Find the message bubble or wrapper
    const bubble = msgElement.querySelector('.message-user, .message-assistant, .message-bubble');
    if (!bubble) return;
    
    // Create the indicator element
    const indicator = document.createElement('div');
    indicator.className = 'guardrail-indicator mt-2';
    
    // Create the warning badge
    const badge = document.createElement('button');
    badge.className = 'guardrail-badge inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 transition-colors cursor-pointer';
    badge.setAttribute('aria-expanded', 'false');
    badge.onclick = () => toggleGuardrailDetails(indicator);
    
    // Warning icon
    const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    iconSvg.setAttribute('class', 'w-3.5 h-3.5 text-amber-500');
    iconSvg.setAttribute('fill', 'none');
    iconSvg.setAttribute('viewBox', '0 0 24 24');
    iconSvg.setAttribute('stroke', 'currentColor');
    iconSvg.setAttribute('stroke-width', '2');
    const iconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    iconPath.setAttribute('stroke-linecap', 'round');
    iconPath.setAttribute('stroke-linejoin', 'round');
    iconPath.setAttribute('d', 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z');
    iconSvg.appendChild(iconPath);
    badge.appendChild(iconSvg);
    
    // Badge text - show first policy type or generic message
    const badgeText = document.createElement('span');
    badgeText.textContent = policyTypes.length > 0 ? policyTypes[0] : 'Guardrail triggered';
    badge.appendChild(badgeText);
    
    // Expand icon
    const expandSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    expandSvg.setAttribute('class', 'expand-icon w-3 h-3 text-amber-400 transition-transform');
    expandSvg.setAttribute('fill', 'none');
    expandSvg.setAttribute('viewBox', '0 0 24 24');
    expandSvg.setAttribute('stroke', 'currentColor');
    expandSvg.setAttribute('stroke-width', '2');
    const expandPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    expandPath.setAttribute('stroke-linecap', 'round');
    expandPath.setAttribute('stroke-linejoin', 'round');
    expandPath.setAttribute('d', 'M19 9l-7 7-7-7');
    expandSvg.appendChild(expandPath);
    badge.appendChild(expandSvg);
    
    indicator.appendChild(badge);
    
    // Create expandable details section (hidden by default)
    const details = createGuardrailDetails(source, policyTypes, assessments);
    indicator.appendChild(details);
    
    // Insert indicator after the message content
    bubble.appendChild(indicator);
}

/**
 * Create the expandable details section for guardrail violations.
 * 
 * @param {string} source - "INPUT" or "OUTPUT"
 * @param {Array} policyTypes - Array of triggered policy type strings
 * @param {Array} assessments - Full assessments array
 * @returns {HTMLElement} Details container element
 * 
 * Requirements: 4.4
 */
function createGuardrailDetails(source, policyTypes, assessments) {
    const details = document.createElement('div');
    details.className = 'guardrail-details hidden mt-2 p-3 rounded-lg bg-amber-50 border border-amber-200 text-xs';
    
    // Header
    const header = document.createElement('div');
    header.className = 'font-medium text-amber-800 mb-2';
    header.textContent = source === 'INPUT' ? 'User message would have triggered guardrail' : 'Assistant response would have triggered guardrail';
    details.appendChild(header);
    
    // Policy types list
    if (policyTypes.length > 0) {
        const policiesHeader = document.createElement('div');
        policiesHeader.className = 'text-amber-700 font-medium mt-2 mb-1';
        policiesHeader.textContent = 'Triggered policies:';
        details.appendChild(policiesHeader);
        
        const policiesList = document.createElement('ul');
        policiesList.className = 'list-disc list-inside text-amber-600 space-y-0.5';
        policyTypes.forEach(policy => {
            const li = document.createElement('li');
            li.textContent = policy;
            policiesList.appendChild(li);
        });
        details.appendChild(policiesList);
    }
    
    // Confidence levels from assessments
    const confidenceInfo = extractConfidenceInfo(assessments);
    if (confidenceInfo.length > 0) {
        const confidenceHeader = document.createElement('div');
        confidenceHeader.className = 'text-amber-700 font-medium mt-3 mb-1';
        confidenceHeader.textContent = 'Confidence levels:';
        details.appendChild(confidenceHeader);
        
        const confidenceList = document.createElement('div');
        confidenceList.className = 'space-y-1';
        confidenceInfo.forEach(info => {
            const item = document.createElement('div');
            item.className = 'flex items-center gap-2';
            
            const label = document.createElement('span');
            label.className = 'text-amber-600';
            label.textContent = info.type + ':';
            item.appendChild(label);
            
            const confidence = document.createElement('span');
            confidence.className = getConfidenceBadgeClass(info.confidence);
            confidence.textContent = info.confidence;
            item.appendChild(confidence);
            
            confidenceList.appendChild(item);
        });
        details.appendChild(confidenceList);
    }
    
    // Shadow mode notice
    const notice = document.createElement('div');
    notice.className = 'mt-3 pt-2 border-t border-amber-200 text-amber-500 italic';
    notice.textContent = 'Shadow mode: Content was not blocked';
    details.appendChild(notice);
    
    return details;
}

/**
 * Extract confidence information from assessments.
 * 
 * @param {Array} assessments - Array of assessment objects
 * @returns {Array} Array of {type, confidence} objects
 */
function extractConfidenceInfo(assessments) {
    const confidenceInfo = [];
    
    if (!assessments || !Array.isArray(assessments)) return confidenceInfo;
    
    assessments.forEach(assessment => {
        if (assessment.contentPolicy) {
            const filters = assessment.contentPolicy.filters || [];
            filters.forEach(filter => {
                if (filter.confidence) {
                    confidenceInfo.push({
                        type: filter.type || 'Content',
                        confidence: filter.confidence
                    });
                }
            });
        }
    });
    
    return confidenceInfo;
}

/**
 * Get CSS class for confidence badge based on level.
 * 
 * @param {string} confidence - Confidence level (HIGH, MEDIUM, LOW)
 * @returns {string} CSS class string
 */
function getConfidenceBadgeClass(confidence) {
    const baseClass = 'px-1.5 py-0.5 rounded text-xs font-medium';
    switch (confidence) {
        case 'HIGH':
            return `${baseClass} bg-red-100 text-red-700`;
        case 'MEDIUM':
            return `${baseClass} bg-amber-100 text-amber-700`;
        case 'LOW':
            return `${baseClass} bg-yellow-100 text-yellow-700`;
        default:
            return `${baseClass} bg-gray-100 text-gray-700`;
    }
}

/**
 * Toggle the visibility of guardrail details.
 * 
 * @param {HTMLElement} indicator - The guardrail indicator container
 * 
 * Requirements: 4.4
 */
function toggleGuardrailDetails(indicator) {
    const details = indicator.querySelector('.guardrail-details');
    const badge = indicator.querySelector('.guardrail-badge');
    const expandIcon = badge?.querySelector('.expand-icon');
    
    if (!details) return;
    
    const isHidden = details.classList.contains('hidden');
    
    if (isHidden) {
        details.classList.remove('hidden');
        badge?.setAttribute('aria-expanded', 'true');
        expandIcon?.classList.add('rotate-180');
    } else {
        details.classList.add('hidden');
        badge?.setAttribute('aria-expanded', 'false');
        expandIcon?.classList.remove('rotate-180');
    }
}

/**
 * Filter out thinking tags from content.
 * Removes <thinking>...</thinking> blocks from the response.
 * 
 * @param {string} content - Content to filter
 * @returns {string} Filtered content
 */
function filterThinkingTags(content) {
    if (!content) return '';
    // Remove complete thinking tags
    content = content.replace(/<thinking>[\s\S]*?<\/thinking>/g, '');
    // Remove incomplete opening thinking tags at the end (only if it's actually a thinking tag start)
    // Be more conservative - only remove if we're clearly in the middle of a thinking tag
    if (content.includes('<thinking>') && !content.includes('</thinking>')) {
        const thinkingStart = content.lastIndexOf('<thinking>');
        content = content.substring(0, thinkingStart);
    }
    return content;
}

// ============================================================================
// Message Display
// ============================================================================

/**
 * Add a message to the message list.
 * 
 * @param {string} role - Message role ('user' or 'assistant')
 * @param {string} content - Message content
 * 
 * Requirements: 5.4 (style user messages distinctly from assistant)
 */
function addMessage(role, content) {
    const messageList = document.getElementById('message-list');
    const msgId = 'msg-' + role + '-' + Date.now();
    
    const isUser = role === 'user';
    // Distinct styling for user vs assistant (Requirement 5.4)
    const alignClass = isUser ? 'items-end' : 'items-start';
    const bubbleClass = isUser ? 'message-user' : 'message-assistant';
    const maxWidth = isUser ? 'max-w-[85%]' : 'w-full min-w-[50%] sm:min-w-[60%] md:min-w-[65%]';
    
    // Render content - markdown for assistant, escaped for user
    let renderedContent;
    if (isUser) {
        renderedContent = escapeHtml(content);
    } else if (typeof marked !== 'undefined') {
        renderedContent = marked.parse(content);
    } else {
        renderedContent = escapeHtml(content);
    }
    
    const html = `
        <div id="${msgId}" class="mb-6 message-fade-in flex flex-col ${alignClass}">
            <div class="inline-block px-3 sm:px-4 md:px-5 py-2.5 sm:py-3 md:py-3.5 rounded-xl sm:rounded-2xl ${maxWidth} ${bubbleClass}">
                <div class="message-content text-sm sm:text-base leading-relaxed ${isUser ? '' : 'markdown-content'}">
                    ${renderedContent}
                </div>
            </div>
            <div class="flex items-center gap-2 mt-1 px-1 text-xs text-gray-400 ${isUser ? 'justify-end' : 'justify-start'}">
                <span>${new Date().toLocaleTimeString()}</span>
            </div>
        </div>
    `;
    
    messageList.insertAdjacentHTML('beforeend', html);
    
    // Force scroll for user messages, regular scroll for assistant
    if (isUser) {
        forceScrollToBottom();
    } else {
        scrollToBottom();
    }
}

/**
 * Add a streaming message placeholder.
 * 
 * @param {string} msgId - Unique message ID
 */
function addStreamingMessage(msgId) {
    const messageList = document.getElementById('message-list');
    
    const html = `
        <div id="${msgId}" class="mb-6 message-fade-in flex flex-col items-start">
            <div class="message-wrapper w-full min-w-[50%] sm:min-w-[60%] md:min-w-[65%] md:max-w-[85%]">
                <div class="message-bubble relative px-3 sm:px-4 md:px-5 py-2.5 sm:pt-3 md:pt-3.5 rounded-xl sm:rounded-2xl message-assistant streaming-pulse">
                    <div class="streaming-progress-bar mb-3 h-1 bg-primary-100 rounded-full overflow-hidden">
                        <div class="h-full bg-gradient-to-r from-primary-500 to-purple-500 rounded-full progress-animation"></div>
                    </div>
                    <div class="tools-container"></div>
                    <div class="message-content text-sm sm:text-base leading-relaxed">
                        <span class="streaming-cursor"></span>
                    </div>
                    <div class="flex justify-between items-center">
                        <div class="feedback-buttons flex gap-1" style="display: none;">
                            <button class="feedback-btn feedback-positive p-1 text-gray-400 hover:text-green-600 hover:bg-green-50 rounded-lg transition-all" title="Helpful response" data-sentiment="positive">
                                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" />
                                </svg>
                            </button>
                            <button class="feedback-btn feedback-negative p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all" title="Not helpful" data-sentiment="negative">
                                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018c.163 0 .326.02.485.06L17 4m-7 10v5a2 2 0 002 2h.095c.5 0 .905-.405.905-.905 0-.714.211-1.412.608-2.006L17 13V4m-7 10h2m5-10h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5" />
                                </svg>
                            </button>
                        </div>
                        <button class="copy-message-btn p-1 text-primary-500 bg-primary-50 hover:bg-primary-100 rounded-lg transition-all" title="Copy response" style="display: none;">
                            <svg class="copy-icon w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                            <svg class="check-icon w-5 h-5 hidden" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="message-footer flex items-center justify-between mt-1 px-1 text-xs text-gray-400"></div>
            </div>
        </div>
    `;
    
    messageList.insertAdjacentHTML('beforeend', html);
    scrollToBottom();
}

/**
 * Finalize a streaming message.
 * 
 * @param {string} msgId - Message element ID
 * @param {string} content - Final message content
 */
function finalizeMessage(msgId, content) {
    const msgElement = document.getElementById(msgId);
    if (!msgElement) return;
    
    // Remove streaming pulse, progress bar, and cursor
    const bubble = msgElement.querySelector('.message-assistant');
    if (bubble) {
        bubble.classList.remove('streaming-pulse');
        
        // Remove the progress bar
        const progressBar = bubble.querySelector('.streaming-progress-bar');
        if (progressBar) {
            progressBar.remove();
        }
        
        // Remove the streaming cursor
        const cursor = bubble.querySelector('.streaming-cursor');
        if (cursor) {
            cursor.remove();
        }
        
        // Show and wire up the copy button
        const copyBtn = bubble.querySelector('.copy-message-btn');
        if (copyBtn) {
            copyBtn.style.display = '';
            copyBtn.onclick = () => {
                // Get the text content from the message (excluding tool displays)
                const contentDiv = bubble.querySelector('.message-content');
                const textContent = contentDiv ? contentDiv.textContent : content;
                copyToClipboard(copyBtn, textContent);
            };
        }
        
        // Show and wire up feedback buttons (Requirements 1.1, 1.2, 1.3)
        addFeedbackButtons(msgElement, msgId);
    }
    
    // Populate footer with timestamp on left, metrics on right
    const footer = msgElement.querySelector('.message-footer');
    if (footer) {
        // Clear existing content
        footer.textContent = '';
        
        // Add timestamp on left
        const timestamp = document.createElement('span');
        timestamp.textContent = new Date().toLocaleTimeString();
        footer.appendChild(timestamp);
        
        // Add metrics on right if available
        const tokenUsage = msgElement.dataset.tokenUsage;
        if (tokenUsage) {
            try {
                const usage = JSON.parse(tokenUsage);
                const metricsElement = createMetricsElement(usage);
                if (metricsElement) {
                    footer.appendChild(metricsElement);
                }
            } catch (e) {
                console.error('Failed to parse token usage:', e);
            }
        }
    }
}

/**
 * Format metrics for display (returns HTML string - for backward compatibility).
 * 
 * @param {Object} usage - Token usage object with inputTokens, outputTokens, latencyMs
 * @returns {string} HTML string for metrics display
 */
function formatMetrics(usage) {
    if (!usage) return '';
    
    const parts = [];
    
    if (usage.inputTokens !== undefined) {
        parts.push(`<span class="text-primary-500">${escapeHtml(String(usage.inputTokens))} in</span>`);
    }
    
    if (usage.outputTokens !== undefined) {
        parts.push(`<span class="text-primary-500">${escapeHtml(String(usage.outputTokens))} out</span>`);
    }
    
    if (usage.latencyMs !== undefined) {
        const latencySec = (usage.latencyMs / 1000).toFixed(2);
        parts.push(`<span class="text-primary-500">${escapeHtml(latencySec)}s</span>`);
    }
    
    if (parts.length === 0) return '';
    
    return `<span class="px-2 py-0.5 bg-primary-50 rounded-full text-primary-600 font-medium">${parts.join(' • ')}</span>`;
}

/**
 * Create metrics element using safe DOM methods.
 * 
 * @param {Object} usage - Token usage object with inputTokens, outputTokens, latencyMs
 * @returns {HTMLElement|null} Metrics span element or null
 */
function createMetricsElement(usage) {
    if (!usage) return null;
    
    const parts = [];
    
    if (usage.inputTokens !== undefined) {
        parts.push(`${usage.inputTokens} in`);
    }
    
    if (usage.outputTokens !== undefined) {
        parts.push(`${usage.outputTokens} out`);
    }
    
    if (usage.latencyMs !== undefined) {
        const latencySec = (usage.latencyMs / 1000).toFixed(2);
        parts.push(`${latencySec}s`);
    }
    
    if (parts.length === 0) return null;
    
    const container = document.createElement('span');
    container.className = 'px-2 py-0.5 bg-primary-50 rounded-full text-primary-600 font-medium';
    
    parts.forEach((text, index) => {
        const span = document.createElement('span');
        span.className = 'text-primary-500';
        span.textContent = text;
        container.appendChild(span);
        
        if (index < parts.length - 1) {
            container.appendChild(document.createTextNode(' • '));
        }
    });
    
    return container;
}

/**
 * Remove a message from the list.
 * 
 * @param {string} msgId - Message element ID
 */
function removeMessage(msgId) {
    const msgElement = document.getElementById(msgId);
    if (msgElement) msgElement.remove();
}

// ============================================================================
// UI State Management
// ============================================================================

/**
 * Connection states for the chat.
 * - 'ready': Idle, ready to send messages
 * - 'connecting': Initial connection, waiting for runtime provisioning
 * - 'streaming': Actively receiving streamed response
 * - 'error': Connection error occurred
 */
let connectionState = 'ready';

/**
 * Set the connection state of the UI.
 * Updates UI elements to reflect the current connection status.
 * 
 * @param {string} state - Connection state ('ready', 'connecting', 'streaming', 'error')
 * 
 * Requirements: 2.6 (streaming indicator, enable input after completion)
 */
function setConnectionState(state) {
    connectionState = state;
    isStreaming = state === 'connecting' || state === 'streaming';
    
    const input = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const newChatBtn = document.getElementById('new-chat-btn');
    const status = document.getElementById('connection-status');
    const scrollBtn = document.getElementById('scroll-to-bottom-btn');
    const keyboardHints = document.getElementById('keyboard-hints');
    
    // Add/remove streaming class to body for global styling
    if (isStreaming) {
        document.body.classList.add('streaming-active');
    } else {
        document.body.classList.remove('streaming-active');
        // Hide scroll button when not streaming
        if (scrollBtn) scrollBtn.classList.add('hidden');
        // Reset scroll state
        userHasScrolledUp = false;
    }
    
    // Disable/enable input elements
    if (input) input.disabled = isStreaming;
    if (sendBtn) sendBtn.disabled = isStreaming;
    if (logoutBtn) logoutBtn.disabled = isStreaming;
    if (newChatBtn) newChatBtn.disabled = isStreaming;
    
    // Hide/show keyboard hints
    if (keyboardHints) {
        keyboardHints.classList.toggle('hidden', isStreaming);
    }
    
    // Update placeholder text
    if (input) {
        input.placeholder = isStreaming ? 'Waiting for response...' : 'Ask me anything...';
    }
    
    // Update connection status indicator (Requirement 2.6 - streaming indicator)
    if (status) {
        switch (state) {
            case 'connecting':
                status.innerHTML = `
                    <span class="w-2 h-2 rounded-full bg-yellow-500 animate-pulse"></span>
                    <span>Connecting...</span>
                `;
                break;
            case 'streaming':
                status.innerHTML = `
                    <span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                    <span>Streaming...</span>
                `;
                break;
            case 'error':
                status.innerHTML = `
                    <span class="w-2 h-2 rounded-full bg-red-500"></span>
                    <span>Error</span>
                `;
                break;
            case 'ready':
            default:
                status.innerHTML = `
                    <span class="w-2 h-2 rounded-full bg-green-500"></span>
                    <span>Ready</span>
                `;
                break;
        }
    }
    
    // Update logout button styling
    if (logoutBtn) {
        if (isStreaming) {
            logoutBtn.classList.add('bg-gray-700', 'text-gray-500', 'cursor-not-allowed');
            logoutBtn.classList.remove('hover:bg-gray-600');
        } else {
            logoutBtn.classList.remove('bg-gray-700', 'text-gray-500', 'cursor-not-allowed');
            logoutBtn.classList.add('hover:bg-gray-600');
        }
    }
    
    // Update send button styling
    if (sendBtn) {
        if (isStreaming) {
            sendBtn.classList.add('bg-gray-400', 'cursor-not-allowed');
            sendBtn.classList.remove('bg-primary-600', 'hover:bg-primary-700');
        } else {
            sendBtn.classList.remove('bg-gray-400', 'cursor-not-allowed');
            sendBtn.classList.add('bg-primary-600', 'hover:bg-primary-700');
        }
    }
}

/**
 * Last failed message for retry functionality.
 */
let lastFailedMessage = null;

/**
 * Show an error message with optional details and retry button.
 * Uses safe DOM methods to prevent XSS.
 * 
 * @param {string} message - Error message to display
 * @param {string} details - Optional additional error details
 * 
 * Requirements: 9.1, 9.2 (display user-friendly error message, allow retry)
 */
function showError(message, details = '') {
    const container = document.getElementById('error-container');
    if (!container) return;
    
    // Clear existing content
    container.textContent = '';
    
    // Build error UI with safe DOM methods
    const wrapper = document.createElement('div');
    wrapper.className = 'mx-auto max-w-4xl';
    
    const errorBox = document.createElement('div');
    errorBox.className = 'error-message rounded-lg p-4 flex items-start justify-between gap-3';
    
    // Left side: icon + message
    const leftSide = document.createElement('div');
    leftSide.className = 'flex items-start gap-3 flex-1';
    
    // Error icon
    const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    iconSvg.setAttribute('class', 'w-5 h-5 text-red-500 flex-shrink-0 mt-0.5');
    iconSvg.setAttribute('fill', 'none');
    iconSvg.setAttribute('viewBox', '0 0 24 24');
    iconSvg.setAttribute('stroke', 'currentColor');
    const iconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    iconPath.setAttribute('stroke-linecap', 'round');
    iconPath.setAttribute('stroke-linejoin', 'round');
    iconPath.setAttribute('stroke-width', '2');
    iconPath.setAttribute('d', 'M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z');
    iconSvg.appendChild(iconPath);
    leftSide.appendChild(iconSvg);
    
    // Message content
    const messageDiv = document.createElement('div');
    messageDiv.className = 'flex-1';
    
    const messageP = document.createElement('p');
    messageP.className = 'text-sm font-medium text-red-800';
    messageP.textContent = message;
    messageDiv.appendChild(messageP);
    
    if (details) {
        const detailsP = document.createElement('p');
        detailsP.className = 'text-xs text-red-600 mt-1';
        detailsP.textContent = details;
        messageDiv.appendChild(detailsP);
    }
    
    leftSide.appendChild(messageDiv);
    errorBox.appendChild(leftSide);
    
    // Right side: buttons
    const rightSide = document.createElement('div');
    rightSide.className = 'flex items-center gap-2 flex-shrink-0';
    
    // Retry button (if applicable)
    if (lastFailedMessage) {
        const retryBtn = document.createElement('button');
        retryBtn.className = 'px-3 py-1.5 text-xs font-medium rounded-lg bg-red-100 text-red-700 hover:bg-red-200 transition-colors';
        retryBtn.textContent = 'Retry';
        retryBtn.onclick = retryLastMessage;
        rightSide.appendChild(retryBtn);
    }
    
    // Dismiss button
    const dismissBtn = document.createElement('button');
    dismissBtn.className = 'text-red-400 hover:text-red-600';
    dismissBtn.setAttribute('aria-label', 'Dismiss error');
    dismissBtn.onclick = hideError;
    
    const dismissSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    dismissSvg.setAttribute('class', 'w-5 h-5');
    dismissSvg.setAttribute('fill', 'none');
    dismissSvg.setAttribute('viewBox', '0 0 24 24');
    dismissSvg.setAttribute('stroke', 'currentColor');
    const dismissPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    dismissPath.setAttribute('stroke-linecap', 'round');
    dismissPath.setAttribute('stroke-linejoin', 'round');
    dismissPath.setAttribute('stroke-width', '2');
    dismissPath.setAttribute('d', 'M6 18L18 6M6 6l12 12');
    dismissSvg.appendChild(dismissPath);
    dismissBtn.appendChild(dismissSvg);
    rightSide.appendChild(dismissBtn);
    
    errorBox.appendChild(rightSide);
    wrapper.appendChild(errorBox);
    container.appendChild(wrapper);
    container.classList.remove('hidden');
}

/**
 * Retry the last failed message.
 * 
 * Requirements: 2.7 (allow retry on error)
 */
function retryLastMessage() {
    if (!lastFailedMessage) return;
    
    hideError();
    
    // Restore the message to the input and submit
    const input = document.getElementById('message-input');
    if (input) {
        input.value = lastFailedMessage;
        lastFailedMessage = null;
        
        // Trigger form submission
        const form = document.getElementById('chat-form');
        if (form) {
            form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    }
}

/**
 * Hide the error message and reset to ready state.
 */
function hideError() {
    const container = document.getElementById('error-container');
    if (container) {
        container.classList.add('hidden');
        container.innerHTML = '';
    }
    // Reset to ready state if we were in error state
    if (connectionState === 'error') {
        setConnectionState('ready');
    }
}

/**
 * Flag to track if user has manually scrolled up.
 */
let userHasScrolledUp = false;

/**
 * Scroll the message list to the bottom.
 * Uses smooth scrolling and respects user scroll position.
 * 
 * Requirements: 5.2 (auto-scroll behavior)
 */
function scrollToBottom() {
    const messageList = document.getElementById('message-list');
    if (!messageList) return;
    
    // Only auto-scroll if user hasn't scrolled up manually
    if (!userHasScrolledUp) {
        messageList.scrollTo({
            top: messageList.scrollHeight,
            behavior: 'smooth'
        });
    }
}

/**
 * Force scroll to bottom, ignoring user scroll state.
 * Used when user sends a new message.
 */
function forceScrollToBottom() {
    const messageList = document.getElementById('message-list');
    if (!messageList) return;
    
    userHasScrolledUp = false;
    messageList.scrollTo({
        top: messageList.scrollHeight,
        behavior: 'smooth'
    });
}

/**
 * Handle scroll events to detect if user has scrolled up.
 */
function handleMessageListScroll() {
    const messageList = document.getElementById('message-list');
    if (!messageList) return;
    
    const scrollBottom = messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight;
    // Consider user scrolled up if more than 100px from bottom
    userHasScrolledUp = scrollBottom > 100;
    
    // Show/hide scroll-to-bottom button
    const scrollBtn = document.getElementById('scroll-to-bottom-btn');
    if (scrollBtn) {
        if (userHasScrolledUp && isStreaming) {
            scrollBtn.classList.remove('hidden');
        } else {
            scrollBtn.classList.add('hidden');
        }
    }
}

/**
 * Escape HTML special characters.
 * 
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================================
// Feedback Functions
// Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5
// ============================================================================

/**
 * Store for message context data needed for feedback submission.
 * Maps messageId to { userMessage, assistantResponse, toolsUsed }
 */
const messageContextStore = new Map();

/**
 * Add feedback buttons to a finalized assistant message.
 * Positions buttons at bottom left of message bubble, across from copy button.
 * 
 * @param {HTMLElement} msgElement - The message container element
 * @param {string} messageId - Unique identifier for the message
 * 
 * Requirements: 1.1, 1.2, 1.3
 */
function addFeedbackButtons(msgElement, messageId) {
    const bubble = msgElement.querySelector('.message-assistant');
    if (!bubble) return;
    
    const feedbackContainer = bubble.querySelector('.feedback-buttons');
    if (!feedbackContainer) return;
    
    // Show the feedback buttons
    feedbackContainer.style.display = '';
    
    // Store message context for later feedback submission
    const contentDiv = bubble.querySelector('.message-content');
    const assistantResponse = contentDiv ? contentDiv.textContent : '';
    
    // Get tools used from tool cards
    const toolsContainer = bubble.querySelector('.tools-container');
    const toolsUsed = [];
    if (toolsContainer) {
        const toolCards = toolsContainer.querySelectorAll('.tool-card');
        toolCards.forEach(card => {
            const toolName = card.dataset.toolName;
            if (toolName) {
                toolsUsed.push(toolName);
            }
        });
    }
    
    // Find the corresponding user message (previous message in the list)
    const messageList = document.getElementById('message-list');
    const messages = messageList ? messageList.querySelectorAll('[id^="msg-"]') : [];
    let userMessage = '';
    for (let i = 0; i < messages.length; i++) {
        if (messages[i].id === messageId && i > 0) {
            const prevMsg = messages[i - 1];
            const userContent = prevMsg.querySelector('.message-content');
            if (userContent) {
                userMessage = userContent.textContent;
            }
            break;
        }
    }
    
    // Store context for feedback submission
    messageContextStore.set(messageId, {
        userMessage,
        assistantResponse,
        toolsUsed
    });
    
    // Wire up click handlers
    const positiveBtn = feedbackContainer.querySelector('.feedback-positive');
    const negativeBtn = feedbackContainer.querySelector('.feedback-negative');
    
    if (positiveBtn) {
        positiveBtn.onclick = () => handleFeedbackClick(messageId, 'positive');
    }
    if (negativeBtn) {
        negativeBtn.onclick = () => handleFeedbackClick(messageId, 'negative');
    }
}

/**
 * Handle feedback button click.
 * For thumbs up: submit feedback immediately with sentiment "positive".
 * For thumbs down: show feedback prompt modal.
 * 
 * @param {string} messageId - The message being rated
 * @param {string} sentiment - 'positive' or 'negative'
 * 
 * Requirements: 2.1, 2.2, 2.3, 3.1
 */
function handleFeedbackClick(messageId, sentiment) {
    if (sentiment === 'positive') {
        // Submit positive feedback immediately
        submitFeedback(messageId, 'positive', null);
    } else {
        // Show feedback prompt modal for negative feedback
        showFeedbackPrompt(messageId);
    }
}

/**
 * Show feedback prompt modal for negative feedback.
 * Includes text input and Submit/Cancel buttons.
 * 
 * @param {string} messageId - The message being rated
 * 
 * Requirements: 3.1, 3.2, 3.4, 3.5
 */
function showFeedbackPrompt(messageId) {
    // Remove any existing modal
    const existingModal = document.getElementById('feedback-modal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Create modal HTML
    const modalHtml = `
        <div id="feedback-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onclick="closeFeedbackModal(event)">
            <div class="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6" onclick="event.stopPropagation()">
                <h3 class="text-lg font-semibold text-gray-900 mb-2">Share your feedback</h3>
                <p class="text-sm text-gray-600 mb-4">What would have made this response more helpful?</p>
                <textarea 
                    id="feedback-comment" 
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 resize-none"
                    rows="3"
                    placeholder="Your feedback helps us improve..."
                ></textarea>
                <div class="flex justify-end gap-3 mt-4">
                    <button 
                        onclick="closeFeedbackModal()" 
                        class="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                    >
                        Cancel
                    </button>
                    <button 
                        onclick="submitNegativeFeedback('${escapeHtml(messageId)}')" 
                        class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-lg transition-colors"
                    >
                        Submit
                    </button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Focus the textarea
    const textarea = document.getElementById('feedback-comment');
    if (textarea) {
        textarea.focus();
    }
    
    // Handle Escape key to close modal
    document.addEventListener('keydown', handleFeedbackModalKeydown);
}

/**
 * Handle keydown events for feedback modal.
 * Closes modal on Escape key.
 * 
 * @param {KeyboardEvent} event - Keyboard event
 */
function handleFeedbackModalKeydown(event) {
    if (event.key === 'Escape') {
        closeFeedbackModal();
    }
}

/**
 * Close the feedback prompt modal without submitting.
 * 
 * @param {Event} event - Optional click event
 * 
 * Requirements: 3.4
 */
function closeFeedbackModal(event) {
    // If called from backdrop click, only close if clicking the backdrop itself
    if (event && event.target.id !== 'feedback-modal') {
        return;
    }
    
    const modal = document.getElementById('feedback-modal');
    if (modal) {
        modal.remove();
    }
    document.removeEventListener('keydown', handleFeedbackModalKeydown);
}

/**
 * Submit negative feedback from the modal.
 * 
 * @param {string} messageId - The message being rated
 * 
 * Requirements: 3.3, 3.5
 */
function submitNegativeFeedback(messageId) {
    const textarea = document.getElementById('feedback-comment');
    const comment = textarea ? textarea.value.trim() : '';
    
    closeFeedbackModal();
    submitFeedback(messageId, 'negative', comment || null);
}

/**
 * Submit feedback to the backend.
 * Collects message context and POSTs to /api/feedback endpoint.
 * Updates UI state on success.
 * 
 * @param {string} messageId - The message ID
 * @param {string} sentiment - 'positive' or 'negative'
 * @param {string|null} comment - Optional user comment
 * 
 * Requirements: 2.1, 3.3
 */
async function submitFeedback(messageId, sentiment, comment) {
    const context = messageContextStore.get(messageId);
    if (!context) {
        console.error('No context found for message:', messageId);
        return;
    }
    
    const payload = {
        message_id: messageId,
        session_id: getSessionId(),
        user_message: context.userMessage,
        assistant_response: context.assistantResponse,
        tools_used: context.toolsUsed,
        sentiment: sentiment,
        user_comment: comment
    };
    
    try {
        const response = await fetch('/api/feedback', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });
        
        if (response.status === 401) {
            console.log('Session expired, redirecting to login');
            window.location.href = '/auth/login?error=session_expired';
            return;
        }
        
        if (!response.ok) {
            const errorText = await response.text().catch(() => '');
            console.error('Feedback submission failed:', response.status, errorText);
            return;
        }
        
        // Update UI to show selected state
        updateFeedbackButtonState(messageId, sentiment);
        
        console.log('Feedback submitted:', sentiment, 'for message:', messageId);
        
    } catch (error) {
        console.error('Failed to submit feedback:', error);
    }
}

/**
 * Update feedback button styling to show selected state.
 * Disables both buttons after feedback is submitted.
 * 
 * @param {string} messageId - The message ID
 * @param {string} sentiment - 'positive' or 'negative'
 * 
 * Requirements: 2.2, 2.3, 3.5
 */
function updateFeedbackButtonState(messageId, sentiment) {
    const msgElement = document.getElementById(messageId);
    if (!msgElement) return;
    
    const feedbackContainer = msgElement.querySelector('.feedback-buttons');
    if (!feedbackContainer) return;
    
    const positiveBtn = feedbackContainer.querySelector('.feedback-positive');
    const negativeBtn = feedbackContainer.querySelector('.feedback-negative');
    
    // Disable both buttons
    if (positiveBtn) {
        positiveBtn.disabled = true;
        positiveBtn.classList.remove('hover:text-green-600', 'hover:bg-green-50');
        positiveBtn.classList.add('cursor-not-allowed');
    }
    if (negativeBtn) {
        negativeBtn.disabled = true;
        negativeBtn.classList.remove('hover:text-red-600', 'hover:bg-red-50');
        negativeBtn.classList.add('cursor-not-allowed');
    }
    
    // Highlight the selected button
    if (sentiment === 'positive' && positiveBtn) {
        positiveBtn.classList.remove('text-gray-400');
        positiveBtn.classList.add('text-green-600', 'bg-green-50');
    } else if (sentiment === 'negative' && negativeBtn) {
        negativeBtn.classList.remove('text-gray-400');
        negativeBtn.classList.add('text-red-600', 'bg-red-50');
    }
}

// ============================================================================
// Tool Display Functions
// ============================================================================

/**
 * Toggle tool card expand/collapse.
 * 
 * @param {HTMLElement} button - The header button that was clicked
 */
function toggleToolExpand(button) {
    const toolCard = button.closest('.tool-card');
    if (!toolCard) return;
    
    const details = toolCard.querySelector('.tool-details');
    const expandIcon = toolCard.querySelector('.expand-icon');
    
    if (details) {
        details.classList.toggle('hidden');
    }
    if (expandIcon) {
        expandIcon.classList.toggle('rotate-180');
    }
}

/**
 * Copy text to clipboard and show feedback.
 * 
 * @param {HTMLElement} button - The copy button element
 * @param {string} text - Text to copy
 */
function copyToClipboard(button, text) {
    navigator.clipboard.writeText(text).then(() => {
        const copyIcon = button.querySelector('.copy-icon');
        const checkIcon = button.querySelector('.check-icon');
        
        // Switch to checkmark with gray styling
        if (copyIcon && checkIcon) {
            copyIcon.classList.add('hidden');
            checkIcon.classList.remove('hidden');
            button.classList.remove('text-primary-500', 'bg-primary-50', 'hover:bg-primary-100');
            button.classList.add('text-gray-400', 'bg-gray-100');
            
            setTimeout(() => {
                // Revert to copy icon with purple styling
                checkIcon.classList.add('hidden');
                copyIcon.classList.remove('hidden');
                button.classList.remove('text-gray-400', 'bg-gray-100');
                button.classList.add('text-primary-500', 'bg-primary-50', 'hover:bg-primary-100');
            }, 2000);
        }
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

/**
 * Update tools visibility based on count.
 * Shows only first N tools and adds "Show more" button if needed.
 * 
 * @param {HTMLElement} toolsContainer - The tools container element
 */
function updateToolsVisibility(toolsContainer) {
    const toolCards = toolsContainer.querySelectorAll('.tool-card');
    const existingShowMore = toolsContainer.querySelector('.show-more-tools-btn');
    
    // Remove existing show more button
    if (existingShowMore) {
        existingShowMore.remove();
    }
    
    const totalTools = toolCards.length;
    const maxVisible = TOOLS_CONFIG.maxVisibleTools;
    
    if (totalTools <= maxVisible) {
        // Show all tools
        toolCards.forEach(card => card.classList.remove('hidden-tool'));
        return;
    }
    
    // Check if tools are currently expanded
    const isExpanded = toolsContainer.dataset.toolsExpanded === 'true';
    
    if (isExpanded) {
        // Show all tools
        toolCards.forEach(card => card.classList.remove('hidden-tool'));
    } else {
        // Hide tools beyond maxVisible
        toolCards.forEach((card, index) => {
            if (index >= maxVisible) {
                card.classList.add('hidden-tool');
            } else {
                card.classList.remove('hidden-tool');
            }
        });
    }
    
    // Add show more/less button
    const hiddenCount = totalTools - maxVisible;
    const showMoreHtml = `
        <button onclick="toggleShowMoreTools(this)" class="show-more-tools-btn w-full px-4 py-2 text-xs font-medium text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-lg border border-primary-200 transition-colors flex items-center justify-center gap-2 my-1">
            ${isExpanded ? `
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                </svg>
                Show less
            ` : `
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
                Show ${hiddenCount} more tool${hiddenCount > 1 ? 's' : ''}
            `}
        </button>
    `;
    toolsContainer.insertAdjacentHTML('beforeend', showMoreHtml);
}

/**
 * Toggle showing all tools or just the first few.
 * 
 * @param {HTMLElement} button - The show more/less button
 */
function toggleShowMoreTools(button) {
    const toolsContainer = button.closest('.tools-container');
    if (!toolsContainer) return;
    
    const isExpanded = toolsContainer.dataset.toolsExpanded === 'true';
    toolsContainer.dataset.toolsExpanded = isExpanded ? 'false' : 'true';
    
    updateToolsVisibility(toolsContainer);
}

// ============================================================================
// Memory Sidebar
// ============================================================================

/**
 * Flag indicating if memory is currently being refreshed.
 */
let isRefreshingMemory = false;

/**
 * Toggle the memory sidebar visibility.
 * Persists preference to localStorage.
 * 
 * Requirements: 4.6
 */
function toggleMemorySidebar() {
    const sidebar = document.getElementById('memory-sidebar');
    const collapsed = document.getElementById('memory-toggle-collapsed');
    
    if (!sidebar || !collapsed) return;
    
    const isCurrentlyCollapsed = sidebar.classList.contains('hidden');
    
    if (isCurrentlyCollapsed) {
        expandMemorySidebar();
    } else {
        collapseMemorySidebar();
    }
    
    // Persist preference (Requirement 4.6)
    localStorage.setItem(MEMORY_COLLAPSED_KEY, String(!isCurrentlyCollapsed));
}

/**
 * Expand the memory sidebar.
 * Shows the sidebar and hides the collapsed toggle.
 * 
 * @param {boolean} skipRefresh - If true, skip the memory refresh (used during initialization)
 */
function expandMemorySidebar(skipRefresh = false) {
    const sidebar = document.getElementById('memory-sidebar');
    const collapsed = document.getElementById('memory-toggle-collapsed');
    
    if (sidebar) {
        sidebar.classList.remove('hidden');
        sidebar.classList.add('flex');
    }
    if (collapsed) {
        collapsed.classList.add('hidden');
    }
    
    // Refresh memory when expanding (unless skipped during init)
    if (!skipRefresh) {
        refreshMemory();
    }
}

/**
 * Collapse the memory sidebar.
 * Hides the sidebar and shows the collapsed toggle.
 */
function collapseMemorySidebar() {
    const sidebar = document.getElementById('memory-sidebar');
    const collapsed = document.getElementById('memory-toggle-collapsed');
    
    if (sidebar) {
        sidebar.classList.add('hidden');
        sidebar.classList.remove('flex');
    }
    if (collapsed) {
        collapsed.classList.remove('hidden');
    }
}

/**
 * Refresh both event and semantic memory.
 * Shows loading state and animates refresh button.
 * 
 * @param {boolean} forceRefresh - If true, bypass cache and fetch from API
 * 
 * Requirements: 4.4 (refresh button handler)
 */
async function refreshMemory(forceRefresh = false) {
    if (isRefreshingMemory) return;
    
    isRefreshingMemory = true;
    
    // If force refresh, clear the cache first
    if (forceRefresh) {
        clearMemoryCache();
    }
    
    // Animate refresh button
    const refreshBtn = document.getElementById('memory-refresh-btn');
    const refreshIcon = document.getElementById('refresh-icon');
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.classList.add('opacity-50');
    }
    if (refreshIcon) {
        refreshIcon.classList.add('animate-spin');
    }
    
    try {
        // Load all memory types in parallel
        // All memory loading functions are now defined in sidebar.html for proper CSS variable inheritance
        const promises = [];
        
        if (typeof loadEventMemory === 'function') {
            promises.push(loadEventMemory(forceRefresh));
        }
        
        if (typeof loadSemanticMemoryByType === 'function') {
            promises.push(loadSemanticMemoryByType('facts', forceRefresh));
            promises.push(loadSemanticMemoryByType('summaries', forceRefresh));
            promises.push(loadSemanticMemoryByType('preferences', forceRefresh));
        }
        
        await Promise.all(promises);
    } finally {
        isRefreshingMemory = false;
        
        // Stop animation
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.classList.remove('opacity-50');
        }
        if (refreshIcon) {
            refreshIcon.classList.remove('animate-spin');
        }
    }
}

// Memory loading functions (loadEventMemory, loadSemanticMemoryByType) are defined in sidebar.html
// for proper CSS variable inheritance with the theme system

// ============================================================================
// Initialization
// ============================================================================

/**
 * Breakpoint for mobile/desktop sidebar behavior.
 * Below this width, sidebar defaults to collapsed.
 */
const MOBILE_BREAKPOINT = 1024;

/**
 * Initialize the chat application on page load.
 * 
 * Requirements: 3.1, 4.6, 5.2, 5.6, 10.8, 10.9
 */
function initializeChat() {
    // Initialize session (Requirement 3.1)
    initializeSession();
    
    // Initialize model selection (Requirements 10.8, 10.9)
    initializeModelSelection();
    
    // Initialize memory sidebar state (Requirement 4.6)
    initializeMemorySidebar();
    
    // Set up scroll event listener for auto-scroll behavior (Requirement 5.2)
    const messageList = document.getElementById('message-list');
    if (messageList) {
        messageList.addEventListener('scroll', handleMessageListScroll);
    }
    
    // Handle window resize for responsive behavior (Requirement 5.6)
    let resizeTimeout;
    window.addEventListener('resize', () => {
        // Debounce resize events
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(handleWindowResize, 150);
    });
    
    // Initialize textarea keyboard handling and auto-resize
    initializeTextarea();
    
    // Prefetch prompt templates first, then load memory (Requirement 1.2)
    prefetchTemplates().then(() => {
        // Load initial memory after templates are ready (Requirements 4.2, 4.3)
        refreshMemory();
    });
    
    console.log('Chat initialized with session:', getSessionId());
}

/**
 * Initialize textarea with keyboard handling and auto-resize.
 * Enter submits, Shift+Enter creates new line.
 */
function initializeTextarea() {
    const textarea = document.getElementById('message-input');
    if (!textarea) return;
    
    // Handle keyboard events
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            // Enter without Shift - submit the form
            e.preventDefault();
            const form = document.getElementById('chat-form');
            if (form && !isStreaming) {
                form.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        }
        // Shift+Enter - default behavior (new line)
    });
    
    // Auto-resize textarea as content grows
    textarea.addEventListener('input', () => {
        autoResizeTextarea(textarea);
    });
}

/**
 * Auto-resize textarea to fit content.
 * 
 * @param {HTMLTextAreaElement} textarea - The textarea element
 */
function autoResizeTextarea(textarea) {
    // Reset height to auto to get the correct scrollHeight
    textarea.style.height = 'auto';
    // Set height to scrollHeight, with a max of 200px
    const maxHeight = 200;
    const newHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = newHeight + 'px';
    // Show scrollbar if content exceeds max height
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
}

/**
 * Initialize memory sidebar state based on saved preference or screen size.
 * 
 * Requirements: 4.6 (persist preference, default collapsed on mobile, expanded on desktop)
 */
function initializeMemorySidebar() {
    const savedPreference = localStorage.getItem(MEMORY_COLLAPSED_KEY);
    const isMobile = window.innerWidth < MOBILE_BREAKPOINT;
    
    // Determine initial state:
    // 1. If user has saved preference, use it
    // 2. Otherwise, default to collapsed on mobile, expanded on desktop
    let shouldCollapse;
    
    if (savedPreference !== null) {
        // User has a saved preference
        shouldCollapse = savedPreference === 'true';
    } else {
        // No saved preference - use responsive default
        shouldCollapse = isMobile;
    }
    
    if (shouldCollapse) {
        collapseMemorySidebar();
    } else {
        // Skip refresh during init - it will be called after templates load
        expandMemorySidebar(true);
    }
}

/**
 * Handle window resize events for responsive layout.
 * Only auto-adjusts sidebar if user hasn't set a preference.
 * 
 * Requirements: 4.6, 5.6 (responsive layout for mobile)
 */
function handleWindowResize() {
    const savedPreference = localStorage.getItem(MEMORY_COLLAPSED_KEY);
    
    // Only auto-adjust if user hasn't explicitly set a preference
    if (savedPreference === null) {
        const isMobile = window.innerWidth < MOBILE_BREAKPOINT;
        
        if (isMobile) {
            collapseMemorySidebar();
        } else {
            expandMemorySidebar();
        }
    }
}

/**
 * Check if the memory sidebar is currently collapsed.
 * 
 * @returns {boolean} True if sidebar is collapsed
 */
function isMemorySidebarCollapsed() {
    const sidebar = document.getElementById('memory-sidebar');
    return sidebar ? sidebar.classList.contains('hidden') : true;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initializeChat);
