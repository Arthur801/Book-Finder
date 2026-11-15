// First-visit guided tour (plan header-category-onboarding §5, P4). Vanilla JavaScript with no dependency other than the
// optional window.bootstrap, which is used only to open the collapsed navbar on narrow screens. The tour makes no network
// request, submits no form, and never activates a page control: it shows text and moves focus inside its own card.
(function () {
    'use strict';

    var STORAGE_KEY = 'bf.onboarding.v1.status';
    var COMPLETED = 'completed';
    var SKIPPED = 'skipped';
    var CATEGORIES_PATH = '/categories';
    var GUIDE_HASH = '#guide';
    var GUIDE_URL = '/categories#guide';
    var NAVBAR_ID = 'main-navbar';
    var SEARCH_INPUT_ID = 'search-q';
    var SHEET_QUERY = '(max-width: 575.98px)';
    var REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
    var GAP = 12;
    var EDGE = 8;
    var SPOTLIGHT_PAD = 6;
    var NAVBAR_WAIT_MS = 400;
    var BUTTON_ACTIONS = ['start', 'skip', 'prev', 'next', 'finish'];

    var root = null;
    var spotlight = null;
    var card = null;
    var titleEl = null;
    var bodyEl = null;
    var progressEl = null;
    var buttons = {};
    var steps = [];
    var active = false;
    var stepIndex = -1;
    var previousFocus = null;
    var memoryStatus = null;
    var navbarOpenedByTour = null;
    var pendingNavbar = null;
    var frameQueued = false;
    var listening = false;

    // Storage can be blocked (private windows, disabled site data), so every access is guarded. The in-memory copy keeps
    // the welcome card from coming back on this page when the write did not persist.
    function readStatus() {
        var stored = null;
        try {
            stored = window.localStorage.getItem(STORAGE_KEY);
        } catch (error) {
            stored = null;
        }
        return stored === COMPLETED || stored === SKIPPED ? stored : memoryStatus;
    }

    function writeStatus(status) {
        memoryStatus = status;
        try {
            window.localStorage.setItem(STORAGE_KEY, status);
        } catch (error) {
            // Nothing else to do: the in-memory copy above is what this page uses.
        }
    }

    function isCategoriesPath() {
        return window.location.pathname.replace(/\/+$/, '') === CATEGORIES_PATH;
    }

    function isGuideRequest() {
        return window.location.hash === GUIDE_HASH && isCategoriesPath();
    }

    // Only the fragment goes; a category, source or page query string on the URL stays.
    function stripGuideHash() {
        try {
            window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
        } catch (error) {
            // The fragment stays; the tour is already running, so this is harmless.
        }
    }

    function isNarrow() {
        return window.matchMedia ? window.matchMedia(SHEET_QUERY).matches : window.innerWidth < 576;
    }

    function prefersReducedMotion() {
        return Boolean(window.matchMedia && window.matchMedia(REDUCED_MOTION_QUERY).matches);
    }

    function bootstrapCollapse() {
        return window.bootstrap && window.bootstrap.Collapse ? window.bootstrap.Collapse : null;
    }

    function clamp(value, min, max) {
        if (max < min) {
            return min;
        }
        return Math.max(min, Math.min(value, max));
    }

    // A target counts only when it is rendered with a size; a missing, hidden or collapsed anchor yields null.
    function visibleRect(element) {
        if (!element || element.getClientRects().length === 0) {
            return null;
        }
        var rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 ? rect : null;
    }

    function currentTarget() {
        var step = steps[stepIndex];
        return step && step.target ? document.querySelector(step.target) : null;
    }

    function readSteps(list) {
        if (!list) {
            return [];
        }
        return Array.prototype.map.call(list.children, function (item) {
            return {
                kind: item.getAttribute('data-kind'),
                title: item.getAttribute('data-title') || '',
                body: item.getAttribute('data-body') || '',
                bodyAnonymous: item.getAttribute('data-body-anonymous'),
                target: item.getAttribute('data-target')
            };
        });
    }

    function setHidden(element, hidden) {
        element.hidden = hidden;
    }

    function renderStep(index) {
        var step = steps[index];
        var signedIn = root.getAttribute('data-signed-in') === 'true';
        var isLast = index === steps.length - 1;
        var isSpot = step.kind === 'spot';

        titleEl.textContent = step.title;
        bodyEl.textContent = !signedIn && step.bodyAnonymous ? step.bodyAnonymous : step.body;
        progressEl.hidden = !isSpot;
        if (isSpot) {
            progressEl.textContent = '第 ' + index + '／' + (steps.length - 2) + ' 步';
        }

        setHidden(buttons.start, index !== 0);
        setHidden(buttons.skip, isLast);
        setHidden(buttons.prev, index === 0);
        setHidden(buttons.next, index === 0 || isLast);
        setHidden(buttons.finish, !isLast);
    }

    function primaryButtonFor(index) {
        if (index === 0) {
            return buttons.start;
        }
        return index === steps.length - 1 ? buttons.finish : buttons.next;
    }

    function focusPrimary() {
        var button = primaryButtonFor(stepIndex);
        if (button && !button.hidden) {
            button.focus({ preventScroll: true });
        }
    }

    function visibleButtons() {
        return Array.prototype.filter.call(card.querySelectorAll('button'), function (button) {
            return !button.hidden;
        });
    }

    // Scroll the target into view only when it is cut off. On narrow screens the bottom sheet covers the lower 60%, so
    // the target is placed near the top there.
    function revealTarget(target) {
        var rect = target.getBoundingClientRect();
        var narrow = isNarrow();
        var visibleBottom = narrow ? window.innerHeight * 0.4 : window.innerHeight;
        if (rect.top >= 0 && rect.bottom <= visibleBottom) {
            return;
        }
        var options = { block: narrow ? 'start' : 'center' };
        if (!prefersReducedMotion()) {
            options.behavior = 'smooth';
        }
        target.scrollIntoView(options);
    }

    function setSpotlight(rect) {
        spotlight.hidden = false;
        spotlight.style.left = (rect.left - SPOTLIGHT_PAD) + 'px';
        spotlight.style.top = (rect.top - SPOTLIGHT_PAD) + 'px';
        spotlight.style.width = (rect.width + SPOTLIGHT_PAD * 2) + 'px';
        spotlight.style.height = (rect.height + SPOTLIGHT_PAD * 2) + 'px';
    }

    // Beside the target when it fits: below, above, right, left, in that order. Otherwise the bottom centre. Always inside the viewport.
    function placeAnchored(rect) {
        var cardWidth = card.offsetWidth;
        var cardHeight = card.offsetHeight;
        var viewWidth = document.documentElement.clientWidth || window.innerWidth;
        var viewHeight = window.innerHeight;
        var centredLeft = rect.left + rect.width / 2 - cardWidth / 2;
        var candidates = [
            { left: centredLeft, top: rect.bottom + GAP },
            { left: centredLeft, top: rect.top - cardHeight - GAP },
            { left: rect.right + GAP, top: rect.top },
            { left: rect.left - cardWidth - GAP, top: rect.top }
        ];
        var chosen = null;
        for (var i = 0; i < candidates.length && !chosen; i += 1) {
            var c = candidates[i];
            var fits = c.left >= EDGE && c.top >= EDGE
                && c.left + cardWidth <= viewWidth - EDGE && c.top + cardHeight <= viewHeight - EDGE;
            if (fits) {
                chosen = c;
            }
        }
        if (!chosen) {
            chosen = { left: (viewWidth - cardWidth) / 2, top: viewHeight - cardHeight - GAP };
        }
        card.style.left = clamp(chosen.left, EDGE, viewWidth - cardWidth - EDGE) + 'px';
        card.style.top = clamp(chosen.top, EDGE, viewHeight - cardHeight - EDGE) + 'px';
    }

    // Recomputes the spotlight and the card from the current step and the current layout. It is the only place that
    // positions the card, so resize, scroll and navbar changes can all call it.
    function layout() {
        if (!active) {
            return;
        }
        var rect = steps[stepIndex].kind === 'spot' ? visibleRect(currentTarget()) : null;
        var narrow = isNarrow();
        var anchored = rect !== null && !narrow;

        root.classList.toggle('is-spotlight', rect !== null);
        if (rect) {
            setSpotlight(rect);
        } else {
            spotlight.hidden = true;
        }
        card.classList.toggle('is-sheet', narrow);
        card.classList.toggle('is-centered', !anchored);
        if (anchored) {
            placeAnchored(rect);
        } else {
            card.style.left = '';
            card.style.top = '';
        }
    }

    function scheduleLayout() {
        if (frameQueued) {
            return;
        }
        frameQueued = true;
        var raf = window.requestAnimationFrame || function (callback) {
            return window.setTimeout(callback, 16);
        };
        raf(function () {
            frameQueued = false;
            layout();
        });
    }

    function clearPendingNavbar() {
        if (!pendingNavbar) {
            return;
        }
        pendingNavbar.element.removeEventListener('shown', pendingNavbar.onShown);
        window.clearTimeout(pendingNavbar.timer);
        pendingNavbar = null;
    }

    // Opens the collapsed navbar that holds the target (narrow screens). Layout runs once the navbar has opened, or after a
    // short wait when the browser sends no event. Returns false when the target is not in the navbar or Bootstrap is missing.
    function openNavbarFor(target) {
        var navbar = target.closest ? target.closest('#' + NAVBAR_ID) : null;
        var collapse = bootstrapCollapse();
        if (!navbar || !collapse || navbar.classList.contains('show')) {
            return false;
        }
        var index = stepIndex;
        clearPendingNavbar();
        navbarOpenedByTour = navbar;
        var onShown = function () {
            clearPendingNavbar();
            if (active && stepIndex === index) {
                var current = currentTarget();
                if (visibleRect(current)) {
                    revealTarget(current);
                }
                layout();
            }
        };
        pendingNavbar = {
            element: navbar,
            onShown: onShown,
            timer: window.setTimeout(onShown, NAVBAR_WAIT_MS)
        };
        navbar.addEventListener('shown', onShown);
        // toggle:false: the default would toggle the navbar as soon as the Collapse instance is created.
        collapse.getOrCreateInstance(navbar, { toggle: false }).show();
        return true;
    }

    // Puts the navbar back the way the tour found it. Bootstrap ignores hide() while the navbar is still transitioning, so
    // in that case the hide waits for the shown event.
    function restoreNavbar() {
        clearPendingNavbar();
        var navbar = navbarOpenedByTour;
        var collapse = bootstrapCollapse();
        navbarOpenedByTour = null;
        if (!navbar || !collapse) {
            return;
        }
        var hide = function () {
            collapse.getOrCreateInstance(navbar, { toggle: false }).hide();
        };
        if (navbar.classList.contains('collapsing')) {
            var hideWhenShown = function () {
                navbar.removeEventListener('shown', hideWhenShown);
                hide();
            };
            navbar.addEventListener('shown', hideWhenShown);
        } else if (navbar.classList.contains('show')) {
            hide();
        }
    }

    function showCurrentStep() {
        var target = currentTarget();
        if (steps[stepIndex].kind === 'spot' && target && !visibleRect(target) && openNavbarFor(target)) {
            return;
        }
        if (target && visibleRect(target)) {
            revealTarget(target);
        }
        layout();
    }

    function goToStep(index) {
        if (index < 0 || index >= steps.length) {
            return;
        }
        restoreNavbar();
        stepIndex = index;
        renderStep(index);
        showCurrentStep();
        focusPrimary();
    }

    function onKeydown(event) {
        if (!active) {
            return;
        }
        if (event.key === 'Escape' || event.key === 'Esc') {
            event.preventDefault();
            skip();
            return;
        }
        if (event.key !== 'Tab') {
            return;
        }
        var focusable = visibleButtons();
        if (focusable.length === 0) {
            return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        var outside = !card.contains(document.activeElement);
        if (event.shiftKey) {
            if (outside || document.activeElement === first) {
                event.preventDefault();
                last.focus({ preventScroll: true });
            }
        } else if (outside || document.activeElement === last) {
            event.preventDefault();
            first.focus({ preventScroll: true });
        }
    }

    function onFocusIn(event) {
        if (active && !card.contains(event.target)) {
            focusPrimary();
        }
    }

    function addListeners() {
        if (listening) {
            return;
        }
        listening = true;
        window.addEventListener('resize', scheduleLayout);
        window.addEventListener('scroll', scheduleLayout, { passive: true });
        document.addEventListener('keydown', onKeydown);
        document.addEventListener('focusin', onFocusIn);
    }

    function removeListeners() {
        if (!listening) {
            return;
        }
        listening = false;
        window.removeEventListener('resize', scheduleLayout);
        window.removeEventListener('scroll', scheduleLayout);
        document.removeEventListener('keydown', onKeydown);
        document.removeEventListener('focusin', onFocusIn);
    }

    function openCard() {
        active = true;
        previousFocus = document.activeElement;
        root.hidden = false;
        addListeners();
    }

    // Closes the tour and returns focus to the element focused before it opened (or to focusTarget when given).
    function closeTour(focusTarget) {
        if (!active) {
            return;
        }
        active = false;
        restoreNavbar();
        removeListeners();
        stepIndex = -1;
        root.classList.remove('is-spotlight');
        spotlight.hidden = true;
        card.classList.remove('is-centered', 'is-sheet');
        card.style.left = '';
        card.style.top = '';
        root.hidden = true;

        var returnTo = focusTarget || previousFocus;
        previousFocus = null;
        if (returnTo && typeof returnTo.focus === 'function' && document.body.contains(returnTo)) {
            returnTo.focus({ preventScroll: true });
        }
    }

    // Skipping never overwrites a completed status, so replaying the tour cannot downgrade it.
    function skip() {
        if (!active) {
            return;
        }
        if (readStatus() !== COMPLETED) {
            writeStatus(SKIPPED);
        }
        closeTour();
    }

    function finish() {
        if (!active) {
            return;
        }
        writeStatus(COMPLETED);
        closeTour(document.getElementById(SEARCH_INPUT_ID));
    }

    function startSpotlight() {
        if (active) {
            if (stepIndex === 0) {
                goToStep(1);
            }
            return;
        }
        openCard();
        goToStep(1);
    }

    // /categories#guide starts the full tour no matter what is stored, then drops only the fragment.
    function handleGuideHash() {
        if (!isGuideRequest()) {
            return false;
        }
        stripGuideHash();
        startSpotlight();
        return true;
    }

    // The welcome card appears only on the public browse pages (data-onboarding-autostart) and only before any status is stored.
    function maybeAutostart() {
        if (root.getAttribute('data-onboarding-autostart') !== 'true') {
            return;
        }
        if (readStatus() !== null) {
            return;
        }
        openCard();
        goToStep(0);
    }

    // Start from the welcome card: on /categories the spotlight begins here; elsewhere the browser goes to the guide URL.
    function onStart() {
        if (isCategoriesPath()) {
            startSpotlight();
            return;
        }
        closeTour();
        window.location.assign(GUIDE_URL);
    }

    function init() {
        root = document.getElementById('onboarding');
        if (!root) {
            return;
        }
        spotlight = root.querySelector('[data-onboarding-spotlight]');
        card = root.querySelector('.onboarding-card');
        titleEl = root.querySelector('[data-onboarding-title]');
        bodyEl = root.querySelector('[data-onboarding-body]');
        progressEl = root.querySelector('[data-onboarding-progress]');
        steps = readSteps(root.querySelector('.onboarding-steps'));
        buttons = {};
        BUTTON_ACTIONS.forEach(function (action) {
            buttons[action] = root.querySelector('[data-onboarding-action="' + action + '"]');
        });
        if (!spotlight || !card || !titleEl || !bodyEl || !progressEl || steps.length < 3
            || BUTTON_ACTIONS.some(function (action) { return !buttons[action]; })) {
            return;
        }

        buttons.start.addEventListener('click', onStart);
        buttons.skip.addEventListener('click', skip);
        buttons.prev.addEventListener('click', function () { goToStep(stepIndex - 1); });
        buttons.next.addEventListener('click', function () { goToStep(stepIndex + 1); });
        buttons.finish.addEventListener('click', finish);
        window.addEventListener('hashchange', handleGuideHash);

        if (handleGuideHash()) {
            return;
        }
        maybeAutostart();
    }

    // Any failure leaves the page as it was without the tour: the overlay stays hidden and no listeners remain.
    function boot() {
        try {
            init();
        } catch (error) {
            try {
                restoreNavbar();
            } catch (restoreError) {
                // Nothing more to undo.
            }
            active = false;
            removeListeners();
            if (root) {
                root.hidden = true;
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
