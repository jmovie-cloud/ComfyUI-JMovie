import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const managedNodes = new Set([
    "JMovieManagedImage", "JMovieManagedVideo", "JMovieManagedAudio", "JMovieCloudVideo", "JMovieResumeVideo",
]);
let currentDialog;

async function request(action) {
    const response = await api.fetchApi(`/jmovie-cloud/connection/${action}`, {
        method: "POST",
        cache: "no-store",
    });
    if (response.status === 403) {
        throw new Error("Open the local ComfyUI server on localhost to connect JMovie.");
    }
    const state = await response.json();
    if (!response.ok) {
        throw new Error(state.error || "Unable to reach JMovie Cloud.");
    }
    return state;
}

function showConnection() {
    if (currentDialog?.open) return;
    const dialog = document.createElement("dialog");
    currentDialog = dialog;
    dialog.className = "jmovie-connect";
    dialog.setAttribute("aria-labelledby", "jmovie-cloud-title");
    const title = document.createElement("h2");
    title.id = "jmovie-cloud-title";
    title.textContent = "JMovie account";
    const message = document.createElement("p");
    message.className = "jmovie-connect__status";
    message.setAttribute("role", "status");
    const codeField = document.createElement("div");
    codeField.className = "jmovie-connect__code-field";
    codeField.setAttribute("role", "group");
    codeField.setAttribute("aria-label", "Device code");
    codeField.hidden = true;
    const deviceCode = document.createElement("code");
    const copy = document.createElement("button");
    copy.textContent = "Copy code";
    codeField.append(deviceCode, copy);
    const link = document.createElement("a");
    link.className = "jmovie-connect__button jmovie-connect__primary";
    link.textContent = "Open authorization page";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const controls = document.createElement("div");
    controls.className = "jmovie-connect__actions";
    const connect = document.createElement("button");
    connect.className = "jmovie-connect__primary";
    connect.textContent = "Connect JMovie";
    const disconnect = document.createElement("button");
    disconnect.textContent = "Disconnect";
    const close = document.createElement("button");
    close.textContent = "Close";
    controls.append(connect, link, disconnect, close);
    dialog.append(title, message, codeField, controls);

    let timer;
    function render(state) {
        if (!dialog.open) return;
        clearTimeout(timer);
        const code = state.state === "pending" ? state.user_code || deviceCode.textContent : "";
        const changedCode = deviceCode.textContent !== (code || "");
        codeField.hidden = !code;
        if (changedCode) {
            deviceCode.textContent = code || "";
            copy.textContent = "Copy code";
        }
        if (state.verification_url) link.href = state.verification_url;
        link.hidden = state.state !== "pending" || !link.hasAttribute("href");
        connect.hidden = state.state === "connected" || (state.state === "pending" && !!code);
        disconnect.hidden = state.state !== "connected" && state.state !== "pending";
        disconnect.textContent = state.state === "pending" ? "Cancel request" : "Disconnect";
        if (state.state === "pending") {
            const pendingMessage = code
                ? "Enter this device code on JMovie, then return here."
                : "Authorization is pending. Select Connect JMovie to see the code again.";
            if (message.textContent !== pendingMessage) message.textContent = pendingMessage;
            timer = setTimeout(() => change("poll"), 2500);
            return;
        }
        link.removeAttribute("href");
        const messages = {
            connected: "Connected to the JMovie production platform.",
            disconnected: "Connect your JMovie production account to run managed nodes.",
            denied: "Authorization was declined.",
            expired: "Authorization expired. Start a new connection.",
        };
        message.textContent = messages[state.state];
    }

    async function change(action, popup) {
        clearTimeout(timer);
        connect.disabled = disconnect.disabled = true;
        try {
            const result = await request(action);
            render(result);
            if (popup && result.verification_url && dialog.open) {
                popup.location.replace(result.verification_url);
            } else {
                popup?.close();
            }
        } catch (error) {
            popup?.close();
            message.textContent = error.message;
            if (disconnect.hidden) connect.hidden = false;
        } finally {
            connect.disabled = disconnect.disabled = false;
        }
    }

    connect.onclick = () => {
        const popup = window.open("about:blank", "_blank");
        if (popup) popup.opener = null;
        change("start", popup);
    };
    copy.onclick = async () => {
        try {
            await navigator.clipboard.writeText(deviceCode.textContent);
            copy.textContent = "Copied";
        } catch {
            const range = document.createRange();
            range.selectNodeContents(deviceCode);
            const selection = window.getSelection();
            selection?.removeAllRanges();
            selection?.addRange(range);
            copy.textContent = "Code selected";
        }
    };
    disconnect.onclick = () => change("disconnect");
    close.onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
        clearTimeout(timer);
        dialog.remove();
    });
    connect.hidden = disconnect.hidden = link.hidden = true;
    message.textContent = "Checking connection…";
    document.body.append(dialog);
    dialog.showModal();
    change("poll");
}

app.registerExtension({
    name: "JMovie.Cloud.Connection",
    setup() {
        const stylesheet = document.createElement("link");
        stylesheet.rel = "stylesheet";
        stylesheet.href = new URL("./connection.css", import.meta.url).href;
        document.head.append(stylesheet);
    },
    nodeCreated(node) {
        if (!managedNodes.has(node.comfyClass)) return;
        const button = node.addWidget("button", "Connect JMovie", null, showConnection);
        button.serialize = false;
        button.options = { ...button.options, serialize: false };
    },
});
