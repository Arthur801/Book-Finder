// 分類 page: the desktop sidebar can be collapsed. Only the lg+ layout uses the collapsed class, so the mobile drawer
// keeps working through Bootstrap's offcanvas. The preference is remembered in localStorage.
(function () {
    'use strict';

    var STORAGE_KEY = 'bookfinder.categorySidebarCollapsed';
    var COLLAPSED_CLASS = 'is-sidebar-collapsed';
    var HIDE_TEXT = '隱藏分類';
    var SHOW_TEXT = '顯示分類';

    // Storage can be blocked (private windows, disabled site data); then the choice is simply not remembered.
    function readPreference() {
        try {
            return window.localStorage.getItem(STORAGE_KEY) === '1';
        } catch (error) {
            return false;
        }
    }

    function savePreference(collapsed) {
        try {
            window.localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
        } catch (error) {
            // Nothing to do: the sidebar still toggles for this page view.
        }
    }

    function applyState(browser, button, collapsed) {
        browser.classList.toggle(COLLAPSED_CLASS, collapsed);
        button.setAttribute('aria-expanded', String(!collapsed));
        button.textContent = collapsed ? SHOW_TEXT : HIDE_TEXT;
    }

    function init() {
        var browser = document.querySelector('.category-browser');
        var button = document.getElementById('category-sidebar-toggle');
        if (!browser || !button) {
            return;
        }

        applyState(browser, button, readPreference());
        button.addEventListener('click', function () {
            var collapsed = !browser.classList.contains(COLLAPSED_CLASS);
            applyState(browser, button, collapsed);
            savePreference(collapsed);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
