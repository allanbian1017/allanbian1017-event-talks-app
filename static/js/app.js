// Global State
let allUpdates = [];
let currentFilter = 'all';
let searchQuery = '';
let selectedUpdateId = null;

// DOM Elements
const refreshBtn = document.getElementById('refresh-btn');
const searchInput = document.getElementById('search-input');
const clearSearchBtn = document.getElementById('clear-search-btn');
const filterContainer = document.getElementById('filter-buttons-container');
const lastUpdatedText = document.getElementById('last-updated-text');
const notesGrid = document.getElementById('notes-grid');
const loadingSkeleton = document.getElementById('loading-skeleton');
const emptyState = document.getElementById('empty-state');
const errorState = document.getElementById('error-state');
const errorMessage = document.getElementById('error-message');
const retryBtn = document.getElementById('retry-btn');
const resetFiltersBtn = document.getElementById('reset-filters-btn');

// Drawer Elements
const tweetDrawer = document.getElementById('tweet-drawer');
const drawerBackdrop = document.getElementById('drawer-backdrop');
const closeDrawerBtn = document.getElementById('close-drawer-btn');
const tweetTextarea = document.getElementById('tweet-textarea');
const charCount = document.getElementById('char-count');
const charCounterWrapper = document.querySelector('.character-counter');
const drawerDate = document.getElementById('drawer-date');
const drawerBadge = document.getElementById('drawer-badge');
const copyTweetBtn = document.getElementById('copy-tweet-btn');
const sendTweetBtn = document.getElementById('send-tweet-btn');

// Toast Elements
const toast = document.getElementById('toast');
const toastMessage = document.getElementById('toast-message');

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    fetchReleaseNotes(false);
});

// Event Listeners Setup
function setupEventListeners() {
    // Refresh action
    refreshBtn.addEventListener('click', () => fetchReleaseNotes(true));
    retryBtn.addEventListener('click', () => fetchReleaseNotes(true));
    
    // Filtering
    filterContainer.addEventListener('click', handleFilterClick);
    resetFiltersBtn.addEventListener('click', resetFilters);
    
    // Searching
    searchInput.addEventListener('input', handleSearchInput);
    clearSearchBtn.addEventListener('click', clearSearch);
    
    // Drawer Closing
    closeDrawerBtn.addEventListener('click', deselectUpdate);
    drawerBackdrop.addEventListener('click', deselectUpdate);
    
    // Drawer Actions
    tweetTextarea.addEventListener('input', handleTweetTextareaInput);
    copyTweetBtn.addEventListener('click', handleCopyTweet);
    sendTweetBtn.addEventListener('click', handleSendTweet);
}

// Fetch Release Notes from API
async function fetchReleaseNotes(forceRefresh = false) {
    showState('loading');
    deselectUpdate();
    
    // Spin refresh button
    const spinner = refreshBtn.querySelector('.spinner-icon');
    if (spinner) spinner.classList.add('spinning');
    refreshBtn.disabled = true;
    
    try {
        const url = `/api/release-notes${forceRefresh ? '?refresh=true' : ''}`;
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            allUpdates = data.updates;
            lastUpdatedText.textContent = `Last updated: ${data.last_fetched}`;
            
            // Build dynamic filters based on actual categories
            updateFilterButtons();
            
            // Render notes
            renderReleaseNotes();
        } else {
            throw new Error(data.error || 'Unknown server error');
        }
    } catch (error) {
        console.error('Error fetching release notes:', error);
        errorMessage.textContent = `Could not load release notes: ${error.message}`;
        showState('error');
    } finally {
        if (spinner) spinner.classList.remove('spinning');
        refreshBtn.disabled = false;
    }
}

// Dynamic Filter Buttons based on returned data categories
function updateFilterButtons() {
    const categories = new Set(allUpdates.map(up => up.category.toLowerCase()));
    
    // We already have hardcoded filters for Feature, Issue, Changed, Deprecated.
    // If we have categories that aren't in those, they will map to "Update" (badge).
    // Let's filter buttons to keep them clean.
}

// Render release notes with current filters/search applied
function renderReleaseNotes() {
    notesGrid.innerHTML = '';
    
    // Apply filters
    const filteredUpdates = allUpdates.filter(update => {
        // Category Filter
        const categoryMatch = currentFilter === 'all' || 
            (currentFilter === 'issue' && ['issue', 'fix', 'resolved'].includes(update.category.toLowerCase())) ||
            (currentFilter === 'feature' && update.category.toLowerCase() === 'feature') ||
            (currentFilter === 'changed' && update.category.toLowerCase() === 'changed') ||
            (currentFilter === 'deprecated' && update.category.toLowerCase() === 'deprecated');
            
        // Search Filter
        const textToSearch = `${update.date} ${update.category} ${update.text}`.toLowerCase();
        const searchMatch = !searchQuery || textToSearch.includes(searchQuery);
        
        return categoryMatch && searchMatch;
    });
    
    if (filteredUpdates.length === 0) {
        showState('empty');
        return;
    }
    
    // Create and append cards
    filteredUpdates.forEach(update => {
        const card = createCardElement(update);
        notesGrid.appendChild(card);
    });
    
    showState('content');
}

// Create Card DOM Element
function createCardElement(update) {
    const card = document.createElement('div');
    card.className = `note-card ${selectedUpdateId === update.id ? 'selected' : ''}`;
    card.setAttribute('data-id', update.id);
    
    const catClass = update.category.toLowerCase();
    let badgeClass = 'badge-update';
    if (catClass.includes('feature')) badgeClass = 'badge-feature';
    else if (catClass.includes('issue') || catClass.includes('fix')) badgeClass = 'badge-issue';
    else if (catClass.includes('change')) badgeClass = 'badge-changed';
    else if (catClass.includes('deprecat')) badgeClass = 'badge-deprecated';
    
    card.innerHTML = `
        <div class="card-header">
            <div class="card-meta">
                <span class="meta-date">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                        <line x1="16" y1="2" x2="16" y2="6"></line>
                        <line x1="8" y1="2" x2="8" y2="6"></line>
                        <line x1="3" y1="10" x2="21" y2="10"></line>
                    </svg>
                    ${update.date}
                </span>
                <span class="badge ${badgeClass}">${update.category}</span>
            </div>
            <div class="select-indicator">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            </div>
        </div>
        <div class="card-body">
            ${update.html}
        </div>
        <div class="card-footer">
            <div class="card-action-links">
                ${update.link ? `
                    <a href="${update.link}" target="_blank" class="action-link" onclick="event.stopPropagation();">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                        </svg>
                        Official Release Note
                    </a>
                ` : ''}
            </div>
            <button class="tweet-action-btn" onclick="event.stopPropagation();">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                </svg>
                <span>Tweet</span>
            </button>
        </div>
    `;
    
    // Add Click listener to card to select it
    card.addEventListener('click', () => {
        if (selectedUpdateId === update.id) {
            deselectUpdate();
        } else {
            selectUpdate(update);
        }
    });
    
    // Add listener specifically to Tweet button inside card
    const tweetBtn = card.querySelector('.tweet-action-btn');
    tweetBtn.addEventListener('click', () => {
        selectUpdate(update);
    });
    
    return card;
}

// UI state switcher
function showState(state) {
    loadingSkeleton.style.display = state === 'loading' ? 'block' : 'none';
    notesGrid.style.display = state === 'content' ? 'grid' : 'none';
    emptyState.style.display = state === 'empty' ? 'flex' : 'none';
    errorState.style.display = state === 'error' ? 'flex' : 'none';
}

// Handle Category Filter Buttons Click
function handleFilterClick(e) {
    const button = e.target.closest('.filter-btn');
    if (!button) return;
    
    // Toggle active class
    filterContainer.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
    button.classList.add('active');
    
    currentFilter = button.getAttribute('data-category');
    renderReleaseNotes();
}

// Handle Search Input
function handleSearchInput(e) {
    searchQuery = e.target.value.toLowerCase().trim();
    clearSearchBtn.style.display = searchQuery.length > 0 ? 'block' : 'none';
    renderReleaseNotes();
}

// Clear Search Input
function clearSearch() {
    searchInput.value = '';
    searchQuery = '';
    clearSearchBtn.style.display = 'none';
    searchInput.focus();
    renderReleaseNotes();
}

// Reset all filters
function resetFilters() {
    currentFilter = 'all';
    searchQuery = '';
    searchInput.value = '';
    clearSearchBtn.style.display = 'none';
    
    filterContainer.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('data-category') === 'all') {
            btn.classList.add('active');
        }
    });
    
    renderReleaseNotes();
}

// Select an update to tweet
function selectUpdate(update) {
    selectedUpdateId = update.id;
    
    // Update card classes
    document.querySelectorAll('.note-card').forEach(card => {
        if (card.getAttribute('data-id') === update.id) {
            card.classList.add('selected');
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
            card.classList.remove('selected');
        }
    });
    
    // Configure drawer details
    drawerDate.textContent = update.date;
    drawerBadge.textContent = update.category;
    
    // Format badge styling
    drawerBadge.className = 'badge';
    const catClass = update.category.toLowerCase();
    if (catClass.includes('feature')) drawerBadge.classList.add('badge-feature');
    else if (catClass.includes('issue') || catClass.includes('fix')) drawerBadge.classList.add('badge-issue');
    else if (catClass.includes('change')) drawerBadge.classList.add('badge-changed');
    else if (catClass.includes('deprecat')) drawerBadge.classList.add('badge-deprecated');
    else drawerBadge.classList.add('badge-update');
    
    // Generate optimized Tweet text (truncated properly to respect 280-char limit)
    const formattedTweet = generateDefaultTweet(update);
    tweetTextarea.value = formattedTweet;
    updateTweetTextarea(formattedTweet);
    
    // Slide up drawer
    tweetDrawer.classList.add('active');
}

// Deselect current update and slide drawer down
function deselectUpdate() {
    selectedUpdateId = null;
    document.querySelectorAll('.note-card').forEach(card => {
        card.classList.remove('selected');
    });
    
    // Slide down drawer
    tweetDrawer.classList.remove('active');
}

// Generate an optimized default tweet that fits the 280 character limit
function generateDefaultTweet(update) {
    const header = `BigQuery Update (${update.date}) - ${update.category}:\n`;
    const linkPlaceholder = `\n\nRead more: https://docs.cloud.google.com/bigquery/docs/release-notes`;
    
    // Total character budget for the body text
    const twitterLinkLength = 23;
    const computedLinkTextLength = `\n\nRead more: `.length + twitterLinkLength;
    const budget = 280 - header.length - computedLinkTextLength;
    
    let bodyText = update.text;
    
    // Truncate if exceeds budget
    if (bodyText.length > budget) {
        bodyText = bodyText.substring(0, budget - 3);
        const lastSpace = bodyText.lastIndexOf(' ');
        if (lastSpace > 0) {
            bodyText = bodyText.substring(0, lastSpace);
        }
        bodyText += '...';
    }
    
    const link = update.link || "https://docs.cloud.google.com/bigquery/docs/release-notes";
    return `${header}${bodyText}\n\nRead more: ${link}`;
}

// Handle manual edits to the Tweet text
function handleTweetTextareaInput(e) {
    updateTweetTextarea(e.target.value);
}

// Update character counter and color alerts
function updateTweetTextarea(text) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    let computedLength = text.length;
    const urls = text.match(urlRegex);
    
    if (urls) {
        urls.forEach(url => {
            computedLength = computedLength - url.length + 23;
        });
    }
    
    charCount.textContent = computedLength;
    
    // Color states
    charCounterWrapper.className = 'character-counter';
    if (computedLength > 280) {
        charCounterWrapper.classList.add('danger');
        sendTweetBtn.disabled = true;
    } else if (computedLength > 250) {
        charCounterWrapper.classList.add('warning');
        sendTweetBtn.disabled = false;
    } else {
        sendTweetBtn.disabled = false;
    }
}

// Copy Tweet content to clipboard
function handleCopyTweet() {
    const text = tweetTextarea.value;
    navigator.clipboard.writeText(text).then(() => {
        showToast("Tweet text copied to clipboard!");
    }).catch(err => {
        console.error('Failed to copy text: ', err);
        tweetTextarea.select();
        document.execCommand('copy');
        showToast("Tweet text copied to clipboard!");
    });
}

// Send tweet - Opens Twitter Web Intent in a new tab
function handleSendTweet() {
    const text = tweetTextarea.value;
    const tweetUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`;
    window.open(tweetUrl, '_blank', 'noopener,noreferrer');
}

// Toast notification helper
let toastTimeout;
function showToast(message) {
    toastMessage.textContent = message;
    toast.classList.add('active');
    
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => {
        toast.classList.remove('active');
    }, 3000);
}
