// Library controls on the Book detail page and on /library (user-library.md §5; ui-flow.md §1, §3.5). This file only
// sends requests and switches state on markup the server rendered: the labels, the star buttons, the error texts and
// the 400 messages all come from the server. Nothing here decides a rule; the server validates every change.
(function () {
    'use strict';

    var API_URL_PREFIX = '/api/library/';
    var UNAUTHORIZED = 401;
    var BAD_REQUEST = 400;
    var NO_CONTENT = 204;

    // The values last confirmed by the server, per controls block. A failed change puts these back, because the
    // select has already shown the new value by the time the request fails.
    var confirmedValues = new WeakMap();

    // The antiforgery token the page renders once (the Book page's section, or the list on /library).
    function getAntiforgeryToken() {
        var input = document.querySelector('input[name="__RequestVerificationToken"]');
        return input ? input.value : '';
    }

    function sendRequest(method, bookId, body) {
        var headers = { RequestVerificationToken: getAntiforgeryToken() };
        var options = { method: method, credentials: 'same-origin', headers: headers };
        if (body !== undefined) {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }
        return fetch(API_URL_PREFIX + encodeURIComponent(bookId), options);
    }

    // Sends the visitor to log in and back to this page. The URL is the one the server rendered on the control.
    function redirectToLogin(loginUrl) {
        window.location.assign(loginUrl);
    }

    // The status and rating currently shown. A rating is the number of pressed stars, or null when none is pressed.
    function readValues(controls) {
        var rating = 0;
        controls.querySelectorAll('[data-library-rating]').forEach(function (star) {
            if (star.getAttribute('aria-pressed') === 'true') {
                rating += 1;
            }
        });
        return {
            readingStatus: controls.querySelector('[data-library-status]').value,
            rating: rating > 0 ? rating : null,
        };
    }

    // Shows a status and rating (null = unrated): selects the option, sets each star's aria-pressed, and enables Clear
    // only when there is a rating.
    function applyValues(controls, values) {
        controls.querySelector('[data-library-status]').value = values.readingStatus;
        controls.querySelectorAll('[data-library-rating]').forEach(function (star) {
            var value = Number(star.getAttribute('data-library-rating'));
            star.setAttribute('aria-pressed', String(values.rating !== null && value <= values.rating));
        });
        controls.querySelector('[data-library-clear-rating]').disabled = values.rating === null;
    }

    // Remembers the values the server confirmed and shows them.
    function commitValues(controls, values) {
        confirmedValues.set(controls, values);
        applyValues(controls, values);
    }

    function restoreConfirmedValues(controls) {
        applyValues(controls, confirmedValues.get(controls));
    }

    // While a request is in flight the controls cannot be used. Clear also stays off when there is no rating to clear.
    function setBusy(controls, busy) {
        controls.querySelectorAll('[data-library-status], [data-library-rating], [data-library-remove]').forEach(function (element) {
            element.disabled = busy;
        });
        controls.querySelector('[data-library-clear-rating]').disabled = busy || confirmedValues.get(controls).rating === null;
    }

    function showError(line, message) {
        line.textContent = message;
        line.hidden = false;
    }

    function hideError(line) {
        line.textContent = '';
        line.hidden = true;
    }

    // The first message the server gave, in the order the controls are laid out. Null when the problem has none.
    function firstValidationMessage(problem) {
        var errors = problem && problem.errors ? problem.errors : {};
        var fields = ['readingStatus', 'rating', ''];
        for (var index = 0; index < fields.length; index += 1) {
            var messages = errors[fields[index]];
            if (messages && messages.length > 0) {
                return messages[0];
            }
        }
        return null;
    }

    function getErrorLine(controls) {
        return controls.querySelector('[data-library-error]');
    }

    // Puts the confirmed values back and shows one message on the controls.
    function failEdit(controls, message) {
        restoreConfirmedValues(controls);
        setBusy(controls, false);
        showError(getErrorLine(controls), message);
    }

    // A non-200 answer to an edit. 401 goes to login; 400 shows the server's message; anything else is a general failure.
    function handleEditFailure(controls, response) {
        if (response.status === UNAUTHORIZED) {
            redirectToLogin(controls.getAttribute('data-login-url'));
            return Promise.resolve();
        }
        var failedText = getErrorLine(controls).getAttribute('data-failed-text');
        if (response.status === BAD_REQUEST) {
            return response.json().then(function (problem) {
                failEdit(controls, firstValidationMessage(problem) || failedText);
            });
        }
        failEdit(controls, failedText);
        return Promise.resolve();
    }

    // Sends one PATCH and shows the server's answer. The controls change only after a 200 (or are put back on failure).
    function patchEntry(controls, change) {
        var bookId = controls.getAttribute('data-book-id');
        hideError(getErrorLine(controls));
        setBusy(controls, true);

        sendRequest('PATCH', bookId, change)
            .then(function (response) {
                if (response.status !== 200) {
                    return handleEditFailure(controls, response);
                }
                return response.json().then(function (entry) {
                    commitValues(controls, { readingStatus: entry.readingStatus, rating: entry.rating });
                    setBusy(controls, false);
                });
            })
            .catch(function () {
                failEdit(controls, getErrorLine(controls).getAttribute('data-failed-text'));
            });
    }

    // Removes the Entry. On /library the row goes, and the empty state appears if no row is left. On the Book page the
    // controls give way to the add button.
    function removeEntry(controls) {
        var bookId = controls.getAttribute('data-book-id');
        hideError(getErrorLine(controls));
        setBusy(controls, true);

        sendRequest('DELETE', bookId)
            .then(function (response) {
                if (response.status !== NO_CONTENT) {
                    return handleEditFailure(controls, response);
                }
                showRemoved(controls);
                return null;
            })
            .catch(function () {
                failEdit(controls, getErrorLine(controls).getAttribute('data-failed-text'));
            });
    }

    function showRemoved(controls) {
        var row = controls.closest('.library-item');
        if (row) {
            row.remove();
            if (!document.querySelector('.library-item')) {
                document.querySelector('.library-empty').hidden = false;
            }
            return;
        }

        // The stale values stay in the hidden controls until the next add, whose 200 overwrites them.
        setBusy(controls, false);
        controls.hidden = true;
        var addButton = document.querySelector('[data-library-add]');
        addButton.disabled = false;
        addButton.hidden = false;
    }

    // Book page: adds the Book (PUT). 200 shows the controls with the entry; 401 goes to login.
    function addToLibrary(button) {
        var controls = document.querySelector('[data-library-controls]');
        var addError = document.querySelector('[data-library-add-error]');
        button.disabled = true;
        hideError(addError);

        sendRequest('PUT', button.getAttribute('data-book-id'))
            .then(function (response) {
                if (response.status === UNAUTHORIZED) {
                    redirectToLogin(button.getAttribute('data-login-url'));
                    return null;
                }
                if (response.status !== 200) {
                    throw new Error('Unexpected status ' + response.status);
                }
                return response.json().then(function (entry) {
                    commitValues(controls, { readingStatus: entry.readingStatus, rating: entry.rating });
                    controls.hidden = false;
                    button.hidden = true;
                });
            })
            .catch(function () {
                button.disabled = false;
                showError(addError, addError.getAttribute('data-failed-text'));
            });
    }

    function bindControls(controls) {
        confirmedValues.set(controls, readValues(controls));

        controls.addEventListener('change', function (event) {
            if (event.target.hasAttribute('data-library-status')) {
                patchEntry(controls, { readingStatus: event.target.value });
            }
        });

        controls.addEventListener('click', function (event) {
            var button = event.target.closest('button');
            if (!button || !controls.contains(button)) {
                return;
            }
            if (button.hasAttribute('data-library-rating')) {
                patchEntry(controls, { rating: Number(button.getAttribute('data-library-rating')) });
            } else if (button.hasAttribute('data-library-clear-rating')) {
                patchEntry(controls, { rating: null });
            } else if (button.hasAttribute('data-library-remove')) {
                removeEntry(controls);
            }
        });
    }

    document.querySelectorAll('[data-library-controls]').forEach(bindControls);

    var addButton = document.querySelector('[data-library-add]');
    if (addButton) {
        addButton.addEventListener('click', function () {
            addToLibrary(addButton);
        });
    }
})();
