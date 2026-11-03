import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const inboxJs = readFileSync(
    resolve(here, "../../operator_panel/static/operator_panel/js/file-share-inbox.js"),
    "utf8",
);
const appJs = readFileSync(
    resolve(here, "../../operator_panel/static/operator_panel/js/app.js"),
    "utf8",
);
const inboxTemplate = readFileSync(
    resolve(here, "../../operator_panel/templates/operator_panel/file_share_inbox.html"),
    "utf8",
);
const sidebarTemplate = readFileSync(
    resolve(here, "../../operator_panel/templates/operator_panel/sidebar.html"),
    "utf8",
);

test("mailbox unread badge refreshes on load, websocket events, visibility and polling", () => {
    assert.match(inboxJs, /counts_only=1/);
    assert.match(inboxJs, /window\.setInterval\(refreshUnreadCount, 10000\)/);
    assert.match(inboxJs, /df:file-share-notification/);
    assert.match(inboxJs, /visibilitychange/);
    assert.match(appJs, /new CustomEvent\("df:file-share-notification"/);
    assert.match(sidebarTemplate, /id="df-file-share-unread-badge"/);
});

test("file-share notification deep link opens its matching received message", () => {
    assert.match(inboxJs, /get\("message_id"\)/);
    assert.match(inboxJs, /payload\.messages\.find/);
    assert.match(inboxTemplate, /id="df-share-inbox"/);
});

test("file metadata is rendered readably without exposing internal identifiers or raw JSON", () => {
    assert.match(inboxJs, /file\.field_label/);
    assert.match(inboxJs, /formatBytes/);
    assert.match(inboxJs, /formatContentType/);
    assert.match(inboxJs, /df-share-inbox-file-details/);
    assert.doesNotMatch(inboxJs, /JSON\.stringify\(message\.form_snapshot/);
    assert.doesNotMatch(inboxJs, /field_code/);
    assert.doesNotMatch(inboxJs, /row_id/);
});

test("interaction types and message statuses are translated for recipients", () => {
    assert.match(inboxJs, /VIEW: "اشتراک‌گذاری برای مشاهده"/);
    assert.match(inboxJs, /REVIEW: "درخواست بررسی یا تأیید فایل"/);
    assert.match(inboxJs, /PENDING: "خوانده‌نشده"/);
});
