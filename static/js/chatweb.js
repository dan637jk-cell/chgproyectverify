function scrollToBottom() {
    const chatHistory = document.getElementById('chat-history');
    if (chatHistory) chatHistory.scrollTop = chatHistory.scrollHeight;
}

// Robust URL normalizer to avoid malformed absolute URLs (e.g., http://host:portpath)
function normalizeWebsiteUrl(u) {
    try {
        return new URL(u, window.location.origin).toString();
    } catch (e) {
        try {
            const m = (u || '').match(/^(https?:\/\/[^/]+)(.*)$/i);
            if (m) {
                const host = m[1];
                let rest = m[2] || '';
                if (rest && !rest.startsWith('/')) rest = '/' + rest;
                return host + rest;
            }
        } catch (_) {}
        const path = (u || '').startsWith('/') ? u : '/' + (u || '');
        return window.location.origin + path;
    }
}

// Attachment queue (URLs uploaded to server)
const pendingImageUrls = [];

async function loadHistory() {
    try {
        const response = await fetch('/history');
        const data = await response.json();
        const historyContent = document.getElementById('history-content');
        if (!historyContent) return;
        historyContent.innerHTML = '';

        if (data.chats && data.chats.length > 0) {
            const chatsTitle = document.createElement('h3');
            chatsTitle.className = 'text-lg font-semibold mt-4';
            chatsTitle.textContent = (window.i18n && i18n.t) ? i18n.t('chats_header') : 'Chats';
            historyContent.appendChild(chatsTitle);
            data.chats.forEach(chat => {
                const chatElement = document.createElement('div');
                chatElement.className = 'flex justify-between items-center p-2 hover:bg-gray-700 rounded';
                const a = document.createElement('a');
                a.href = `/chat/${chat.hashchat}`;
                a.className = 'block flex-grow';
                a.textContent = chat.title;
                const btn = document.createElement('button');
                btn.className = 'delete-chat-btn text-red-500 hover:text-red-700';
                btn.dataset.hashchat = chat.hashchat;
                btn.innerHTML = '<i class="fas fa-trash"></i>';
                chatElement.appendChild(a);
                chatElement.appendChild(btn);
                historyContent.appendChild(chatElement);
            });
        }

        if (data.websites && data.websites.length > 0) {
            const websitesTitle = document.createElement('h3');
            websitesTitle.className = 'text-lg font-semibold mt-4';
            websitesTitle.textContent = (window.i18n && i18n.t) ? i18n.t('websites_header') : 'Websites';
            historyContent.appendChild(websitesTitle);
            data.websites.forEach(site => {
                const siteUrl = normalizeWebsiteUrl(site.url);
                const siteElement = document.createElement('div');
                siteElement.className = 'flex justify-between items-center p-2 hover:bg-gray-700 rounded';

                const link = document.createElement('a');
                link.href = siteUrl;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.className = 'block flex-grow';
                link.textContent = site.name;

                const actions = document.createElement('div');
                const republishBtn = document.createElement('button');
                republishBtn.className = 'republish-btn-history text-sm text-blue-400';
                republishBtn.dataset.url = siteUrl;
                republishBtn.dataset.name = site.name;
                republishBtn.textContent = (window.i18n && i18n.t) ? i18n.t('republish') : 'Republish';

                const editBtn = document.createElement('button');
                editBtn.className = 'edit-btn-history text-sm text-green-400 ml-2';
                editBtn.dataset.url = siteUrl;
                editBtn.textContent = (window.i18n && i18n.t) ? i18n.t('edit') : 'Edit';

                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete-website-btn text-sm text-red-500 ml-2';
                deleteBtn.dataset.name = site.name;
                deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';

                actions.appendChild(republishBtn);
                actions.appendChild(editBtn);
                actions.appendChild(deleteBtn);

                siteElement.appendChild(link);
                siteElement.appendChild(actions);
                historyContent.appendChild(siteElement);
            });

            document.querySelectorAll('.republish-btn-history').forEach(button => {
                button.addEventListener('click', (e) => {
                    const url = e.currentTarget.dataset.url;
                    const name = e.currentTarget.dataset.name;
                    publishWebsite(true, url, name);
                });
            });

            document.querySelectorAll('.edit-btn-history').forEach(button => {
                button.addEventListener('click', async (e) => {
                    const url = e.currentTarget.dataset.url;
                    try {
                        const fixedUrl = normalizeWebsiteUrl(url);
                        const response = await fetch(fixedUrl, { cache: 'no-store' });
                        if (!response.ok) throw new Error(`HTTP ${response.status}`);
                        const html = await response.text();
                        if (!html || html.startsWith('about:blank')) throw new Error('Empty HTML');
                        sessionStorage.setItem('htmlToEdit', html);
                        window.location.href = '/chat';
                    } catch (error) {
                        console.error('Error fetching HTML for editing:', error);
                        const title = (window.i18n && i18n.t) ? i18n.t('error_title') : 'Error';
                        const msg = (window.i18n && i18n.t) ? i18n.t('could_not_load_for_editing') : 'Could not load the website content for editing.';
                        Swal.fire(title, msg, 'error');
                    }
                });
            });
        }

        addDeleteEventListeners();

    } catch (error) {
        console.error('Error loading history:', error);
    }
}

function addDeleteEventListeners() {
    document.querySelectorAll('.delete-chat-btn').forEach(button => {
        button.addEventListener('click', async (e) => {
            const hashchat = e.currentTarget.dataset.hashchat;
            const result = await Swal.fire({
                title: (window.i18n && i18n.t) ? i18n.t('confirm_title') : 'Are you sure?',
                text: (window.i18n && i18n.t) ? i18n.t('confirm_text_irreversible') : "You won't be able to revert this!",
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#3085d6',
                cancelButtonColor: '#d33',
                confirmButtonText: (window.i18n && i18n.t) ? i18n.t('confirm_yes_delete') : 'Yes, delete it!'
            });

            if (result.isConfirmed) {
                const response = await fetch('/delete_chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hashchat })
                });
                const data = await response.json();
                if (data.success) {
                    Swal.fire(
                        (window.i18n && i18n.t) ? i18n.t('deleted_title') : 'Deleted!',
                        (window.i18n && i18n.t) ? i18n.t('chat_deleted') : 'Your chat has been deleted.',
                        'success'
                    );
                    loadHistory();
                } else {
                    Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', data.error, 'error');
                }
            }
        });
    });

    document.querySelectorAll('.delete-website-btn').forEach(button => {
        button.addEventListener('click', async (e) => {
            const name = e.currentTarget.dataset.name;
            const result = await Swal.fire({
                title: (window.i18n && i18n.t) ? i18n.t('confirm_title') : 'Are you sure?',
                text: (window.i18n && i18n.t) ? i18n.t('confirm_text_irreversible') : "You won't be able to revert this!",
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#3085d6',
                cancelButtonColor: '#d33',
                confirmButtonText: (window.i18n && i18n.t) ? i18n.t('confirm_yes_delete') : 'Yes, delete it!'
            });

            if (result.isConfirmed) {
                const response = await fetch('/delete_website', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                const data = await response.json();
                if (data.success) {
                    Swal.fire(
                        (window.i18n && i18n.t) ? i18n.t('deleted_title') : 'Deleted!',
                        (window.i18n && i18n.t) ? i18n.t('website_deleted') : 'Your website has been deleted.',
                        'success'
                    );
                    loadHistory();
                } else {
                    Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', data.error, 'error');
                }
            }
        });
    });

    const deleteAllChatsBtn = document.getElementById('delete-all-chats-btn');
    if (deleteAllChatsBtn) {
        deleteAllChatsBtn.addEventListener('click', async () => {
            const result = await Swal.fire({
                title: (window.i18n && i18n.t) ? i18n.t('confirm_title') : 'Are you sure?',
                text: (window.i18n && i18n.t) ? i18n.t('delete_all_text') : 'You are about to delete all your chat history. This action cannot be undone.',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#d33',
                cancelButtonColor: '#3085d6',
                confirmButtonText: (window.i18n && i18n.t) ? i18n.t('yes_delete_all') : 'Yes, delete all!'
            });

            if (result.isConfirmed) {
                const response = await fetch('/delete_all_chats', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    Swal.fire(
                        (window.i18n && i18n.t) ? i18n.t('deleted_title') : 'Deleted!',
                        (window.i18n && i18n.t) ? i18n.t('all_chats_deleted') : 'All your chats have been deleted.',
                        'success'
                    );
                    loadHistory();
                } else {
                    Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', data.error, 'error');
                }
            }
        });
    }
}


async function publishWebsite(republish = false, url = null, name = null) {
    let htmlContent;
    let websiteName;

    const webFrame = document.getElementById('webFrame');
    if (webFrame && webFrame.contentDocument && webFrame.contentDocument.documentElement) {
        try {
            htmlContent = webFrame.contentDocument.documentElement.outerHTML;
        } catch (e) {
            console.warn('Editor content not readable, will try URL if republishing.', e);
        }
    }

    if (republish && !htmlContent && url) {
        try {
            const response = await fetch(normalizeWebsiteUrl(url), { cache: 'no-store' });
            htmlContent = await response.text();
        } catch (error) {
            console.error('Error fetching content for republishing:', error);
            Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', (window.i18n && i18n.t) ? i18n.t('could_not_load_for_editing') : 'Could not load the website content for editing.', 'error');
            return;
        }
    }

    if (!republish && !htmlContent) {
        Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', (window.i18n && i18n.t) ? i18n.t('could_not_publish') : 'Could not publish the site:', 'error');
        return;
    }

    if (!republish) {
        const { value: inputName } = await Swal.fire({
            title: (window.i18n && i18n.t) ? i18n.t('enter_website_name_title') : 'Enter a name for your website',
            input: 'text',
            inputLabel: (window.i18n && i18n.t) ? i18n.t('input_label_website_name') : 'Website Name',
            inputPlaceholder: (window.i18n && i18n.t) ? i18n.t('input_placeholder_website_name') : 'My Awesome Site',
            showCancelButton: true,
            inputValidator: (value) => {
                if (!value) {
                    return (window.i18n && i18n.t) ? i18n.t('input_validation_required') : 'You need to write something!';
                }
            }
        });
        websiteName = inputName;
    } else {
        websiteName = name;
    }

    if (!websiteName) return;

    try {
        const response = await fetch('/publish_website', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ html_content: htmlContent, website_name: websiteName, republish: !!republish })
        });

        const data = await response.json();

        if (data.success) {
            Swal.fire({
                title: (window.i18n && i18n.t) ? (republish ? i18n.t('site_republished_title') : i18n.t('site_published_title')) : (republish ? 'Site Republished!' : 'Site Published!'),
                text: `${(window.i18n && i18n.t) ? i18n.t('site_available_text') : 'Your website is available at:'} ${data.url}`,
                icon: 'success',
                confirmButtonText: (window.i18n && i18n.t) ? i18n.t('copy_link') : 'Copy Link',
                showCancelButton: true,
                cancelButtonText: (window.i18n && i18n.t) ? i18n.t('close') : 'Close'
            }).then((result) => {
                if (result.isConfirmed) {
                    navigator.clipboard.writeText(data.url).then(() => {
                        Swal.fire((window.i18n && i18n.t) ? i18n.t('link_copied_title') : 'Link Copied!', '', 'success');
                    });
                }
            });
            loadHistory();
        } else {
            let errorMsg = `${(window.i18n && i18n.t) ? i18n.t('could_not_publish') : 'Could not publish the site:'} ${data.error}`;
            if (data.recharge_url) {
                Swal.fire({
                    title: (window.i18n && i18n.t) ? i18n.t('error_title') : 'Error',
                    html: `${errorMsg}<br><br><a href="${data.recharge_url}" target="_blank" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">${(window.i18n && i18n.t) ? i18n.t('recharge_balance') : 'Recharge Balance'}</a>`,
                    icon: 'error'
                });
            } else {
                Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', errorMsg, 'error');
            }
        }
    } catch (error) {
        console.error('Publish error:', error);
        Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', (window.i18n && i18n.t) ? i18n.t('network_error') : 'A network error occurred. Please try again.', 'error');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const chatHistory = document.getElementById('chat-history');
    const aiLoadingIndicator = document.getElementById('ai-loading-indicator');

    // Camera upload handling (multi-image + previews)
    const cameraBtn = document.getElementById('chat-call-btn');
    if (cameraBtn) {
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = 'image/*';
        fileInput.capture = 'environment';
        fileInput.multiple = true;
        fileInput.style.display = 'none';
        document.body.appendChild(fileInput);

        cameraBtn.addEventListener('click', () => fileInput.click());

        fileInput.addEventListener('change', async () => {
            if (!fileInput.files || fileInput.files.length === 0) return;

            for (const file of Array.from(fileInput.files)) {
                if (!file.type || !file.type.startsWith('image/')) {
                    Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', (window.i18n && i18n.t) ? i18n.t('images_only') : 'Only images are allowed', 'error');
                    continue;
                }
                const formData = new FormData();
                formData.append('image', file);
                try {
                    const res = await fetch('/upload_image', { method: 'POST', body: formData });
                    const data = await res.json();
                    if (!data.success) {
                        Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', data.error || ((window.i18n && i18n.t) ? i18n.t('upload_failed') : 'Upload failed'), 'error');
                        continue;
                    }
                    pendingImageUrls.push(data.url);
                    const preview = document.createElement('div');
                    preview.className = 'inline-block mr-1 mb-1';
                    preview.innerHTML = `<img src="${data.url}" alt="img" class="inline-block w-12 h-12 object-cover rounded border border-gray-600" />`;
                    const previewContainerId = 'pending-previews';
                    let cont = document.getElementById(previewContainerId);
                    if (!cont) {
                        cont = document.createElement('div');
                        cont.id = previewContainerId;
                        cont.className = 'w-full flex flex-wrap justify-end';
                        const inputRow = document.getElementById('input-row') || messageInput.parentElement;
                        inputRow.parentElement.insertBefore(cont, inputRow);
                    }
                    cont.appendChild(preview);
                } catch (e) {
                    console.error(e);
                    Swal.fire((window.i18n && i18n.t) ? i18n.t('error_title') : 'Error', (window.i18n && i18n.t) ? i18n.t('network_error') : 'A network error occurred. Please try again.', 'error');
                }
            }
            fileInput.value = '';
            scrollToBottom();
        });
    }

    async function sendMessage() {
        const message = messageInput ? messageInput.value.trim() : '';
        if ((!message || message === '') && pendingImageUrls.length === 0) return;

        const webFrame = document.getElementById('webFrame');
        const current_html = webFrame && webFrame.contentDocument ? webFrame.contentDocument.documentElement.outerHTML : '';

        const userVisible = message;

        if (messageInput) messageInput.value = '';
        if (chatHistory) {
            if (pendingImageUrls.length > 0) {
                const imgs = pendingImageUrls.map(u => `<img src="${u}" class="inline-block w-16 h-16 object-cover rounded mr-1 mb-1 border border-gray-600" />`).join('');
                chatHistory.innerHTML += `<div class="text-right my-2"><div class="inline-block bg-blue-600 p-2 rounded-lg">${imgs}${userVisible ? `<div class='mt-1'>${userVisible.replace(/</g,'&lt;')}</div>` : ''}</div></div>`;
            } else if (userVisible) {
                chatHistory.innerHTML += `<div class="text-right my-2"><span class="bg-blue-600 p-2 rounded-lg inline-block">${userVisible.replace(/</g,'&lt;')}</span></div>`;
            }
        }
        scrollToBottom();
        if (aiLoadingIndicator) aiLoadingIndicator.style.display = 'flex';

        try {
            const response = await fetch('/chat/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    hashchat: typeof HASHCHAT !== 'undefined' ? HASHCHAT : '',
                    message: userVisible,
                    usernickname: typeof USERNAME !== 'undefined' ? USERNAME : '',
                    current_html: current_html,
                    url_images: pendingImageUrls,
                }),
            });

            const data = await response.json();
            if (data.success) {
                pendingImageUrls.length = 0;
                const cont = document.getElementById('pending-previews');
                if (cont) cont.remove();
                updateChatHistory();
            } else {
                let errorMsg = `${(window.i18n && i18n.t) ? i18n.t('error_title') : 'Error'}: ${data.error}`;
                if (chatHistory) {
                    if (data.recharge_url) {
                        chatHistory.innerHTML += `<div class="text-left my-2"><span class="bg-red-700 p-2 rounded-lg inline-block">${errorMsg} <a href="${data.recharge_url}" target="_blank" class="text-white underline">${(window.i18n && i18n.t) ? i18n.t('recharge_balance') : 'Recharge Balance'}</a></span></div>`;
                    } else {
                        chatHistory.innerHTML += `<div class="text-left my-2"><span class="bg-red-700 p-2 rounded-lg inline-block">${errorMsg}</span></div>`;
                    }
                }

                if (data.error === 'Unauthorized') {
                    window.location.href = '/login';
                }
            }
        } catch (error) {
            console.error('Error sending message:', error);
            if (chatHistory) chatHistory.innerHTML += `<div class="text-left my-2"><span class="bg-red-700 p-2 rounded-lg inline-block">${(window.i18n && i18n.t) ? i18n.t('connection_error') : 'Connection error.'}</span></div>`;
        } finally {
            if (aiLoadingIndicator) aiLoadingIndicator.style.display = 'none';
            scrollToBottom();
        }
    }

    async function updateChatHistory() {
        const chatHistory = document.getElementById('chat-history');
        if (!chatHistory) return;
        try {
            const response = await fetch('/update_messages_history', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hashsesion: typeof HASHCHAT !== 'undefined' ? HASHCHAT : '', len_list_history: chatHistory.children.length }),
            });
            const messages = await response.json();
            if (messages.error && messages.error === 'Unauthorized') {
                window.location.href = '/login';
                return;
            }
            if (messages.message !== "not_update_history_chat") {
                chatHistory.innerHTML = '';
                messages.forEach(msg => {
                    if (msg.deploy_item) {
                        const webFrame = document.getElementById('webFrame');
                        const doc = webFrame.contentDocument || webFrame.contentWindow.document;
                        doc.open();
                        doc.write(msg.message);
                        doc.close();
                    } else {
                        if (msg.role === 'user') {
                            chatHistory.innerHTML += `<div class="text-right my-2"><span class="bg-blue-600 p-2 rounded-lg inline-block">${msg.message}</span></div>`;
                        } else {
                            chatHistory.innerHTML += `<div class="text-left my-2"><span class="bg-gray-700 p-2 rounded-lg inline-block">${msg.message}</span></div>`;
                        }
                    }
                });
                scrollToBottom();
            }
        } catch (error) {
            console.error('Error updating chat history:', error);
        }
    }

    if (sendButton && messageInput) {
        sendButton.addEventListener('click', sendMessage);
        messageInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
    }


    const publishButtons = document.querySelectorAll('.publish-btn');
    if (publishButtons) {
        publishButtons.forEach(button => {
            button.addEventListener('click', () => publishWebsite(false));
        });
    }

    const mobileMenuButton = document.getElementById('mobile-menu-button');
    const mobileMenu = document.getElementById('mobile-menu');

    if (mobileMenuButton && mobileMenu) {
        mobileMenuButton.addEventListener('click', () => {
            mobileMenu.classList.toggle('hidden');
        });
    }

    // --- Fullscreen Preview Logic ---
    const showPreviewBtn = document.getElementById('show-preview-btn');
    const fullscreenPreview = document.getElementById('fullscreen-preview');
    const closePreviewBtn = document.getElementById('close-preview-btn');
    const fullscreenIframe = document.getElementById('fullscreen-iframe');
    const webFrame = document.getElementById('webFrame');

    if (webFrame) {
        const htmlToEdit = sessionStorage.getItem('htmlToEdit');
        if (htmlToEdit) {
            const doc = webFrame.contentDocument || webFrame.contentWindow.document;
            doc.open();
            doc.write(htmlToEdit);
            doc.close();
            sessionStorage.removeItem('htmlToEdit');
        }
    }

    if (showPreviewBtn && fullscreenIframe && fullscreenPreview && webFrame) {
        showPreviewBtn.addEventListener('click', () => {
            const currentContent = webFrame.contentDocument.documentElement.outerHTML;
            fullscreenIframe.setAttribute('sandbox', 'allow-same-origin allow-scripts');
            fullscreenIframe.srcdoc = currentContent;
            fullscreenPreview.style.display = 'block';
        });
    }

    if (closePreviewBtn && fullscreenPreview) {
        closePreviewBtn.addEventListener('click', () => {
            fullscreenPreview.style.display = 'none';
            if (fullscreenIframe) fullscreenIframe.srcdoc = '';
        });
    }

    // Initial loads
    loadHistory();
});
