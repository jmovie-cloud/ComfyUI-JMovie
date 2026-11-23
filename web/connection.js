import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const managedNodes = new Set(["JMovieManagedImage", "JMovieCloudVideo", "JMovieResumeVideo"]);
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
    dialog.setAttribute("aria-labelledby", "jmovie-cloud-title");
    dialog.style.cssText = "position:fixed;inset:0;margin:auto;width:min(420px,90vw);height:fit-content;pointer-events:auto;padding:22px;border:1px solid var(--border-color);border-radius:8px;background:var(--comfy-menu-bg);color:var(--input-text);";
    const title = document.createElement("h2");
    title.id = "jmovie-cloud-title";
    title.textContent = "JMovie Cloud";
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    const link = document.createElement("a");
    link.textContent = "Open JMovie authorization";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const controls = document.createElement("div");
    controls.style.cssText = "display:flex;gap:8px;margin-top:18px";
    const connect = document.createElement("button");
    connect.textContent = "Connect JMovie";
    const disconnect = document.createElement("button");
    disconnect.textContent = "Disconnect";
    const close = document.createElement("button");
    close.textContent = "Close";
    controls.append(connect, disconnect, close);
    dialog.append(title, status, link, controls);

    let timer;
    function render(state) {
        if (!dialog.open) return;
        clearTimeout(timer);
        const code = state.user_code || dialog.dataset.userCode;
        if (state.user_code) dialog.dataset.userCode = state.user_code;
        if (state.verification_url) link.href = state.verification_url;
        link.hidden = state.state !== "pending" || !link.hasAttribute("href");
        connect.hidden = state.state === "connected" || (state.state === "pending" && !!code);
        disconnect.hidden = state.state !== "connected" && state.state !== "pending";
        if (state.state === "pending") {
            status.textContent = code
                ? `Confirm code ${code} on the JMovie page, then return here.`
                : "Authorization is pending. Select Connect JMovie to see the code again.";
            timer = setTimeout(() => change("poll"), 2500);
            return;
        }
        delete dialog.dataset.userCode;
        link.removeAttribute("href");
        const messages = {
            connected: "Connected to the JMovie production platform.",
            disconnected: "Connect your JMovie production account to run managed nodes.",
            denied: "Authorization was declined.",
            expired: "Authorization expired. Start a new connection.",
        };
        status.textContent = messages[state.state];
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
            status.textContent = error.message;
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
    disconnect.onclick = () => change("disconnect");
    close.onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
        clearTimeout(timer);
        dialog.remove();
    });
    connect.hidden = disconnect.hidden = link.hidden = true;
    status.textContent = "Checking connection…";
    document.body.append(dialog);
    dialog.showModal();
    change("poll");
}

app.registerExtension({
    name: "JMovie.Cloud.Connection",
    nodeCreated(node) {
        if (!managedNodes.has(node.comfyClass)) return;
        const button = node.addWidget("button", "Connect JMovie", null, showConnection);
        button.serialize = false;
        button.options = { ...button.options, serialize: false };
    },
});
