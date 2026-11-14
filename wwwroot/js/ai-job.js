// The /ai/jobs/{id} page (plan async-recommendation-jobs section 3.8). While the job is QUEUED or RUNNING the page polls its status
// every 3 seconds, but only while the tab is visible. When the job reaches SUCCEEDED or FAILED the page reloads, so the server renders the
// final state and its message: no message text lives in this script.
(function () {
    'use strict';

    var INTERVAL_MS = 3000;

    var root = document.getElementById('ai-job');
    if (!root) {
        return;
    }

    var statusUrl = root.getAttribute('data-job-status-url');
    var status = root.getAttribute('data-job-status');
    if (!statusUrl || (status !== 'QUEUED' && status !== 'RUNNING')) {
        return;
    }

    var timer = null;
    var inFlight = false;

    function stop() {
        if (timer !== null) {
            window.clearInterval(timer);
            timer = null;
        }
    }

    function start() {
        if (timer === null) {
            timer = window.setInterval(poll, INTERVAL_MS);
        }
    }

    function poll() {
        if (inFlight || document.visibilityState !== 'visible') {
            return;
        }
        inFlight = true;
        fetch(statusUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (response) {
                // A failed request is ignored: the next tick asks again.
                return response.ok ? response.json() : null;
            })
            .then(function (body) {
                if (body && (body.status === 'SUCCEEDED' || body.status === 'FAILED')) {
                    stop();
                    window.location.reload();
                }
            })
            .catch(function () {
                // Network error: nothing to do, the next tick retries.
            })
            .then(function () {
                inFlight = false;
            });
    }

    // Leaving the tab stops polling; coming back checks at once and resumes the interval.
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            poll();
            start();
        } else {
            stop();
        }
    });

    if (document.visibilityState === 'visible') {
        start();
    }
})();
