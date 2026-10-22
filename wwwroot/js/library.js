// Book detail page: the Library section (user-library.md §5; ui-flow.md §3.3). This file only sends the request and
// swaps the section's markup. Which Books can be added and what the first status is are decided on the server.
(function () {
    'use strict';

    var API_URL_PREFIX = '/api/library/';
    var LOGIN_PATH = '/account/login';
    var PENDING_ACTION = 'add-to-library';
    var ADD_FAILED_TEXT = '加入失敗，請稍後再試';
    var UNRATED_TEXT = '未評分';
    var STATUS_LABELS = {
        WANT_TO_READ: '想讀',
        READING: '閱讀中',
        FINISHED: '已讀',
    };

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

    function getSection() {
        return document.getElementById('library');
    }

    // The antiforgery token rendered inside the section, the same value a browser posts back for the form.
    function getAntiforgeryToken() {
        var input = getSection().querySelector('input[name="__RequestVerificationToken"]');
        return input ? input.value : '';
    }

    // Sends the visitor to log in, and from there back to this Book page, which then adds it (identity-auth.md §6).
    function redirectToLogin() {
        var returnUrl = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.assign(LOGIN_PATH + '?returnUrl=' + returnUrl + '&pendingAction=' + PENDING_ACTION);
    }

    // The same markup the server renders for a Book in the Library (_LibrarySection.cshtml), so the page looks alike.
    function renderStatus(entry) {
        var status = createElement('div', 'library-status');
        var label = STATUS_LABELS[entry.readingStatus] || entry.readingStatus;
        status.appendChild(createElement('p', 'mb-1', '書單狀態：' + label));

        var rating = UNRATED_TEXT;
        if (typeof entry.rating === 'number') {
            rating = '★'.repeat(entry.rating) + '☆'.repeat(5 - entry.rating);
        }
        status.appendChild(createElement('p', 'library-rating mb-0', rating));
        return status;
    }

    function showError(text) {
        var error = getSection().querySelector('.library-error');
        if (error) {
            error.textContent = text;
            error.hidden = false;
        }
    }

    function hideError() {
        var error = getSection().querySelector('.library-error');
        if (error) {
            error.textContent = '';
            error.hidden = true;
        }
    }

    // Replaces the whole section, so the add button and its token are removed along with the error line.
    function showEntry(entry) {
        getSection().replaceChildren(renderStatus(entry));
    }

    function putLibraryEntry(bookId) {
        return fetch(API_URL_PREFIX + encodeURIComponent(bookId), {
            method: 'PUT',
            credentials: 'same-origin',
            headers: { RequestVerificationToken: getAntiforgeryToken() },
        });
    }

    function addToLibrary(button) {
        var bookId = button.getAttribute('data-book-id');
        button.disabled = true;
        hideError();

        putLibraryEntry(bookId)
            .then(function (response) {
                if (response.status === 401) {
                    // The session expired or was never there: go through login and come back to add the Book.
                    redirectToLogin();
                    return null;
                }
                if (response.status !== 200) {
                    throw new Error('Unexpected status ' + response.status);
                }
                return response.json();
            })
            .then(function (entry) {
                if (entry) {
                    showEntry(entry);
                }
            })
            .catch(function () {
                button.disabled = false;
                showError(ADD_FAILED_TEXT);
            });
    }

    function bindAddButton(button) {
        button.addEventListener('click', function () {
            addToLibrary(button);
        });
    }

    var addButton = document.querySelector('[data-library-add]');
    if (addButton) {
        bindAddButton(addButton);
    }
})();
