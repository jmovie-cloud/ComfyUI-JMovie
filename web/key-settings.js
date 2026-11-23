import { api } from "../../scripts/api.js";

const providers = {
    minimax: { name: "MiniMax" },
    openai: { name: "OpenAI", keys: "https://platform.openai.com/api-keys" },
};

const minimaxPlatforms = {
    global: { name: "International", keys: "https://platform.minimax.io/console/keys" },
    cn: { name: "Mainland China", keys: "https://platform.minimax.cn/console/keys" },
};

export const byokNodes = {
    JMovieMiniMaxH3: "minimax",
    JMovieCloudImage: "openai",
};

export function keyButtonLabel(provider) {
    return `Set ${providers[provider].name} API key`;
}

async function request(provider, action, key, region) {
    const options = { method: "POST", cache: "no-store" };
    if (action === "save") {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify({ key, region });
    }
    const response = await api.fetchApi(`/jmovie-cloud/keys/${provider}/${action}`, options);
    if (response.status === 403) {
        throw new Error("Open ComfyUI on localhost to manage API keys.");
    }
    const state = await response.json();
    if (!response.ok) throw new Error(state.error || "Could not update the API key.");
    return state;
}

export function showKeySettings(provider) {
    if (document.querySelector(".jmovie-connect[open]")) return;

    const { name, keys } = providers[provider];
    const regional = provider === "minimax";
    const dialog = document.createElement("dialog");
    dialog.className = "jmovie-connect";
    dialog.setAttribute("aria-labelledby", "jmovie-key-title");
    dialog.innerHTML = `
        <h2 id="jmovie-key-title"></h2>
        <p class="jmovie-connect__intro"></p>
        <form autocomplete="off">
            <div data-platform hidden>
                <div class="jmovie-connect__field-heading">
                    <label for="jmovie-minimax-platform">MiniMax platform</label>
                </div>
                <select id="jmovie-minimax-platform" aria-describedby="jmovie-minimax-platform-hint">
                    <option value="global">International</option>
                    <option value="cn">Mainland China</option>
                </select>
                <p id="jmovie-minimax-platform-hint" class="jmovie-connect__status jmovie-connect__platform-hint">
                    Choose the site that issued your API key.
                </p>
            </div>
            <div class="jmovie-connect__field-heading">
                <label for="jmovie-api-key">API key</label>
                <a class="jmovie-connect__text-link" target="_blank" rel="noopener noreferrer"></a>
            </div>
            <input id="jmovie-api-key" type="password" maxlength="4096" autocomplete="off"
                autocapitalize="off" spellcheck="false" aria-describedby="jmovie-key-status">
            <p id="jmovie-key-status" class="jmovie-connect__status jmovie-connect__key-status" role="status"></p>
            <div class="jmovie-connect__actions">
                <button type="submit" class="jmovie-connect__primary">Save API key</button>
                <button type="button" data-close>Close</button>
                <button type="button" data-remove hidden>Remove saved key</button>
            </div>
        </form>
    `;

    const title = dialog.querySelector("h2");
    const intro = dialog.querySelector(".jmovie-connect__intro");
    const link = dialog.querySelector("a");
    const form = dialog.querySelector("form");
    const platform = dialog.querySelector("select");
    const input = dialog.querySelector("input");
    const status = dialog.querySelector("[role=status]");
    const save = dialog.querySelector("[type=submit]");
    const close = dialog.querySelector("[data-close]");
    const remove = dialog.querySelector("[data-remove]");

    title.textContent = `${name} API key`;
    intro.textContent = `Runs are billed to your ${name} account. Your key is saved on this ComfyUI installation.`;
    dialog.querySelector("[data-platform]").hidden = !regional;

    let source = "none";
    let activeRegion = "global";
    let busy = false;

    function switchingPlatform() {
        return regional && platform.value !== activeRegion;
    }

    function renderStatus() {
        const switching = switchingPlatform();
        const selected = minimaxPlatforms[platform.value];
        link.href = regional ? selected.keys : keys;
        link.textContent = regional ? `Get ${selected.name} API key` : `Get API key from ${name}`;
        input.placeholder = source === "none" || switching ? "Paste your API key" : "Paste a new API key to replace it";
        if (switching && source !== "none") {
            status.textContent = `The ${minimaxPlatforms[activeRegion].name} key stays active until you save a new key.`;
            return;
        }
        const messages = {
            saved: "API key saved. You can run this node now.",
            environment: "Using the API key from the ComfyUI startup environment.",
            none: "No API key saved.",
        };
        status.textContent = messages[source];
    }

    function renderActions() {
        const hasInput = !!input.value.trim();
        const switching = switchingPlatform();
        const done = source === "saved" && !hasInput && !busy && !switching;
        input.disabled = busy;
        platform.disabled = busy;
        save.disabled = busy || !hasInput;
        save.hidden = done;
        close.textContent = done ? "Done" : "Close";
        close.classList.toggle("jmovie-connect__primary", done);
        remove.disabled = busy;
        remove.hidden = source !== "saved" || switching;
    }

    async function update(action) {
        if (busy) return;
        busy = true;
        const key = input.value;
        renderActions();
        status.dataset.error = "false";
        status.textContent = { status: "Checking API key…", save: "Saving API key…", remove: "Removing API key…" }[action];
        try {
            const state = await request(provider, action, key, regional ? platform.value : undefined);
            source = state.source;
            if (regional) {
                activeRegion = state.region;
                platform.value = activeRegion;
            }
            input.value = "";
            renderStatus();
        } catch (error) {
            status.dataset.error = "true";
            status.textContent = error instanceof SyntaxError ? "Could not open API key settings." : error.message;
        } finally {
            busy = false;
            renderActions();
            if (dialog.open) (action === "save" && save.hidden ? close : input).focus();
        }
    }

    input.addEventListener("input", renderActions);
    platform.addEventListener("change", () => {
        input.value = "";
        status.dataset.error = "false";
        renderStatus();
        renderActions();
    });
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!save.disabled) update("save");
    });
    remove.onclick = () => update("remove");
    close.onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
        input.value = "";
        dialog.remove();
    }, { once: true });
    document.body.append(dialog);
    dialog.showModal();
    renderStatus();
    update("status");
}
