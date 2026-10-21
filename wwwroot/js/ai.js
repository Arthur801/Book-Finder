// AI recommendation page and the home page's AI entry (ui-flow.md §3.2, §3.4; api-spec.md §3).
// The home form hands the requirement to /ai through sessionStorage, so the text never appears in a URL.
(function () {
    'use strict';

    var STORAGE_KEY = 'bookFinder.aiRequirement';
    var API_URL = '/api/recommendations';
    var LOGIN_URL = '/account/login?returnUrl=%2Fai';
    var SEARCHING_TEXT = 'AI 正在為你找書…（約需 10～30 秒）';
    var EMPTY_TEXT = '請輸入閱讀需求';
    var NO_RESULT_TEXT = '找不到符合的書，試著換個描述';
    var UNAVAILABLE_TEXT = 'AI 推薦暫時無法使用，請稍後再試';

    // Storage can be blocked (private windows, disabled site data); then the text is simply not carried over.
    function saveRequirement(text) {
        try {
            window.sessionStorage.setItem(STORAGE_KEY, text);
        } catch (error) {
            // Nothing to do: the user can type the requirement again.
        }
    }

    function takeRequirement() {
        try {
            var text = window.sessionStorage.getItem(STORAGE_KEY);
            window.sessionStorage.removeItem(STORAGE_KEY);
            return text;
        } catch (error) {
            return null;
        }
    }

    function createElement(tag, className, text) {
        var element = document.createElement(tag);
        if (className) {
            element.className = className;
        }
        if (text !== undefined) {
            element.textContent = text;
        }
        return element;
    }

    // Home page: pass the typed text on to /ai, which reads it once.
    function bindHomeForm(form) {
        var textarea = document.getElementById('ai-request');
        form.addEventListener('submit', function (event) {
            event.preventDefault();
            var text = textarea.value.trim();
            if (text !== '') {
                saveRequirement(text);
            }
            window.location.assign('/ai');
        });
    }

    // The AI page: a requirement handed over from the home page fills the textarea once.
    function bindAiForm(form) {
        var textarea = document.getElementById('ai-requirement');
        var button = document.getElementById('ai-submit');
        var status = document.getElementById('ai-status');
        var results = document.getElementById('ai-results');

        var handedOver = takeRequirement();
        if (handedOver) {
            textarea.value = handedOver;
        }

        function showStatus(text) {
            status.textContent = text;
        }

        function createCover(book) {
            // Only http(s) thumbnails are shown; anything else gets the same placeholder as a missing cover.
            if (book.thumbnailUrl && /^https?:\/\//.test(book.thumbnailUrl)) {
                var image = createElement('img', 'cover');
                image.src = book.thumbnailUrl;
                image.alt = '';
                image.width = 48;
                image.height = 68;
                image.loading = 'lazy';
                image.style.objectFit = 'cover';
                return image;
            }
            var placeholder = createElement('span', 'cover cover-placeholder text-muted small', '無封面');
            placeholder.style.width = '48px';
            return placeholder;
        }

        // Every value comes from the server or the LLM, so it is only ever written as text.
        function createResultItem(item) {
            var book = item.book;
            var row = createElement('li', 'd-flex align-items-start gap-3 py-3 border-bottom');
            var rank = createElement('span', 'fw-bold text-end', String(item.rank));
            rank.style.minWidth = '2.5rem';
            row.appendChild(rank);
            row.appendChild(createCover(book));

            var body = createElement('div', 'flex-grow-1');
            var title = createElement('a', 'book-title', book.title);
            title.href = '/books/' + encodeURIComponent(book.id);
            body.appendChild(title);
            body.appendChild(createElement('div', 'authors text-muted small', (book.authors || []).join('、')));
            body.appendChild(createElement('p', 'reason mb-1', item.reason));

            var difficulty = item.difficulty === null ? '—' : String(item.difficulty);
            var relevance = Math.round(item.relevance * 100);
            body.appendChild(createElement('div', 'text-muted small', '相關度 ' + relevance + '%　難度 ' + difficulty));
            row.appendChild(body);
            return row;
        }

        function renderResults(items) {
            if (items.length === 0) {
                showStatus(NO_RESULT_TEXT);
                return;
            }
            showStatus('');
            items.forEach(function (item) {
                results.appendChild(createResultItem(item));
            });
        }

        // Only a 400 validation problem shows the server's message; every other failure gets the generic one.
        function handleResponse(response, text) {
            if (response.status === 401) {
                // The session expired or was never there: keep the text, sign in, and come back here.
                saveRequirement(text);
                window.location.assign(LOGIN_URL);
                return null;
            }
            if (response.status === 200) {
                return response.json().then(function (body) {
                    renderResults(body.results || []);
                });
            }
            if (response.status === 400) {
                return response.json().then(function (problem) {
                    var messages = problem.type === '/errors/validation' && problem.errors && problem.errors.requirementText;
                    showStatus(messages && messages[0] ? messages[0] : UNAVAILABLE_TEXT);
                });
            }
            showStatus(UNAVAILABLE_TEXT);
            return null;
        }

        function search(text) {
            var token = form.querySelector('input[name="__RequestVerificationToken"]').value;
            button.disabled = true;
            showStatus(SEARCHING_TEXT);
            results.textContent = '';

            fetch(API_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'RequestVerificationToken': token },
                body: JSON.stringify({ requirementText: text }),
                credentials: 'same-origin'
            })
                .then(function (response) {
                    return handleResponse(response, text);
                })
                .catch(function () {
                    showStatus(UNAVAILABLE_TEXT);
                })
                .then(function () {
                    button.disabled = false;
                });
        }

        form.addEventListener('submit', function (event) {
            event.preventDefault();
            var text = textarea.value.trim();
            if (text === '') {
                showStatus(EMPTY_TEXT);
                return;
            }
            search(text);
        });
    }

    var homeForm = document.getElementById('home-ai-form');
    if (homeForm) {
        bindHomeForm(homeForm);
    }

    var aiForm = document.getElementById('ai-form');
    if (aiForm) {
        bindAiForm(aiForm);
    }
})();
